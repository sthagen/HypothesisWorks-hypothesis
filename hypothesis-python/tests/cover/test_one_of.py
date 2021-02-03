# This file is part of Hypothesis, which may be found at
# https://github.com/HypothesisWorks/hypothesis/
#
# Most of this work is copyright (C) 2013-2021 David R. MacIver
# (david@drmaciver.com), but it contains contributions by others. See
# CONTRIBUTING.rst for a full list of people who may hold copyright, and
# consult the git log if you need to determine who owns an individual
# contribution.
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.
#
# END HEADER

import re

import pytest

from hypothesis import given, strategies as st
from hypothesis.errors import InvalidArgument

from tests.common.debug import assert_no_examples


def test_one_of_empty():
    e = st.one_of()
    assert e.is_empty
    assert_no_examples(e)


@given(st.one_of(st.integers().filter(bool)))
def test_one_of_filtered(i):
    assert bool(i)


@given(st.one_of(st.just(100).flatmap(st.integers)))
def test_one_of_flatmapped(i):
    assert i >= 100


def test_one_of_single_strategy_is_noop():
    s = st.integers()
    assert st.one_of(s) is s
    assert st.one_of([s]) is s


def test_one_of_without_strategies_suggests_sampled_from():
    with pytest.raises(
        InvalidArgument,
        match=re.escape("Did you mean st.sampled_from([1, 2, 3])?"),
    ):
        st.one_of(1, 2, 3)
