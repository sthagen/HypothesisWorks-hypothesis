# This file is part of Hypothesis, which may be found at
# https://github.com/HypothesisWorks/hypothesis/
#
# Copyright the Hypothesis Authors.
# Individual contributors are listed in AUTHORS.rst and the git log.
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.

import ast
import inspect
import math
import sys
from ast import AST, Constant, Expr, NodeVisitor, UnaryOp, USub
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, AbstractSet, Optional, TypedDict, Union

from sortedcontainers import SortedSet

from hypothesis.internal.escalation import is_hypothesis_file
from hypothesis.internal.floats import float_to_int

if TYPE_CHECKING:
    from typing import TypeAlias

ConstantT: "TypeAlias" = Union[int, float, bytes, str]


class ConstantsT(TypedDict):
    integer: AbstractSet[int]
    float: AbstractSet[float]
    bytes: AbstractSet[bytes]
    string: AbstractSet[str]


class ConstantVisitor(NodeVisitor):
    def __init__(self):
        super().__init__()
        self.constants: set[ConstantT] = set()

    def _add_constant(self, value: object) -> None:
        if isinstance(value, str) and (
            len(value) > 20 or value.isspace() or value == ""
        ):
            # discard long strings, which are unlikely to be useful.
            return
        if isinstance(value, bytes) and value == b"":
            return
        if isinstance(value, bool):
            return
        if isinstance(value, float) and math.isinf(value):
            # we already upweight inf.
            return
        if isinstance(value, int) and -100 < value < 100:
            # we already upweight small integers.
            return

        if isinstance(value, (int, float, bytes, str)):
            self.constants.add(value)
            return

        # I don't kow what case could go here, but am also not confident there
        # isn't one.
        return  # pragma: no cover

    def visit_UnaryOp(self, node: UnaryOp) -> None:
        # `a = -1` is actually a combination of a USub and the constant 1.
        if (
            isinstance(node.op, USub)
            and isinstance(node.operand, Constant)
            and isinstance(node.operand.value, (int, float))
            and not isinstance(node.operand.value, bool)
        ):
            self._add_constant(-node.operand.value)
            # don't recurse on this node to avoid adding the positive variant
            return

        self.generic_visit(node)

    def visit_Expr(self, node: Expr) -> None:
        if isinstance(node.value, Constant) and isinstance(node.value.value, str):
            return

        self.generic_visit(node)

    def visit_JoinedStr(self, node):
        # dont recurse on JoinedStr, i.e. f strings. Constants that appear *only*
        # in f strings are unlikely to be helpful.
        return

    def visit_Constant(self, node):
        self._add_constant(node.value)
        self.generic_visit(node)


@lru_cache(1024)
def constants_from_ast(tree: AST) -> AbstractSet[ConstantT]:
    visitor = ConstantVisitor()
    visitor.visit(tree)
    return visitor.constants


@lru_cache(1024)
def _module_ast(module: ModuleType) -> Optional[AST]:
    try:
        source = inspect.getsource(module)
        tree = ast.parse(source)
    except Exception:
        return None

    return tree


@lru_cache(4096)
def _is_local_module_file(path: str) -> bool:
    from hypothesis.internal.scrutineer import ModuleLocation

    return (
        # Skip expensive path lookup for stdlib modules.
        # This will cause false negatives if a user names their module the
        # same as a stdlib module.
        #
        # sys.stdlib_module_names is new in 3.10
        not (sys.version_info >= (3, 10) and path in sys.stdlib_module_names)
        and ModuleLocation.from_path(path) is ModuleLocation.LOCAL
        # normally, hypothesis is a third-party library and is not returned
        # by local_modules. However, if it is installed as an editable package
        # with pip install -e, then we will pick up on it. Just hardcode an
        # ignore here.
        and not is_hypothesis_file(path)
        # avoid collecting constants from test files
        and not (
            "test" in (p := Path(path)).parts
            or "tests" in p.parts
            or p.stem.startswith("test_")
            or p.stem.endswith("_test")
        )
    )


def local_modules() -> tuple[ModuleType, ...]:
    if sys.platform == "emscripten":  # pragma: no cover
        # pyodide builds bundle the stdlib in a nonstandard location, like
        # `/lib/python312.zip/heapq.py`. To avoid identifying the entirety of
        # the stdlib as local code and slowing down on emscripten, instead return
        # that nothing is local.
        #
        # pyodide may provide some way to distinguish stdlib/third-party/local
        # code. I haven't looked into it. If they do, we should correctly implement
        # ModuleLocation for pyodide instead of this.
        return ()

    # Prevents a `RuntimeError` that can occur when looping over `sys.modules`
    # if it's simultaneously modified as a side effect of code in another thread.
    # See: https://docs.python.org/3/library/sys.html#sys.modules
    modules = sys.modules.copy().values()

    return tuple(
        module
        for module in modules
        if (
            getattr(module, "__file__", None) is not None
            and _is_local_module_file(module.__file__)
        )
    )


def local_constants() -> ConstantsT:
    constants: set[ConstantT] = set()
    for module in local_modules():
        tree = _module_ast(module)
        if tree is None:  # pragma: no cover
            continue
        constants |= constants_from_ast(tree)

    local_constants: ConstantsT = {
        "integer": SortedSet(),
        "float": SortedSet(key=float_to_int),
        "bytes": SortedSet(),
        "string": SortedSet(),
    }
    for value in constants:
        choice_type = {
            int: "integer",
            float: "float",
            bytes: "bytes",
            str: "string",
        }[type(value)]
        local_constants[choice_type].add(value)  # type: ignore # hard to type

    return local_constants
