from __future__ import annotations

import math

from databricks_to_pbi.validation.compare import is_match, relative_delta

EPS = 1e-6


def test_exact_equal_matches() -> None:
    assert is_match(100.0, 100.0, epsilon=EPS)


def test_small_float_noise_within_tolerance() -> None:
    assert is_match(1_000_000.0, 1_000_000.0001, epsilon=EPS)


def test_large_magnitude_relative_not_absolute() -> None:
    # 1e9 vs 1e9+500: absolute diff 500 is huge, relative diff 5e-7 < 1e-6 -> match
    assert is_match(1_000_000_000.0, 1_000_000_500.0, epsilon=EPS)


def test_real_mismatch_fails() -> None:
    assert not is_match(100.0, 110.0, epsilon=EPS)


def test_small_values_use_floor_of_one() -> None:
    # 0.0 vs 0.0000005: max(|a|,|b|,1)=1 -> delta 5e-7 < 1e-6 -> match
    assert is_match(0.0, 0.0000005, epsilon=EPS)


def test_null_matches_only_null() -> None:
    assert is_match(None, None, epsilon=EPS)
    assert not is_match(None, 0.0, epsilon=EPS)
    assert not is_match(5.0, None, epsilon=EPS)


def test_nan_never_matches() -> None:
    assert not is_match(math.nan, math.nan, epsilon=EPS)
    assert not is_match(1.0, math.nan, epsilon=EPS)


def test_relative_delta_floor() -> None:
    assert relative_delta(0.0, 0.5) == 0.5  # max(0,0.5,1)=1
