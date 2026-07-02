"""Pure numeric comparison with configurable relative tolerance."""

from __future__ import annotations

import math

__all__ = ["DEFAULT_EPSILON", "is_match", "relative_delta"]

DEFAULT_EPSILON = 1e-6


def relative_delta(sql: float, dax: float) -> float:
    """Relative difference with a floor of 1 in the denominator so tiny
    magnitudes don't blow up the ratio."""
    return abs(sql - dax) / max(abs(sql), abs(dax), 1.0)


def is_match(sql: float | None, dax: float | None, *, epsilon: float) -> bool:
    """True iff the two values are equal within ``epsilon`` relative tolerance.

    ``None`` matches only ``None``. ``NaN`` never matches anything.
    """
    if sql is None or dax is None:
        return sql is None and dax is None
    if math.isnan(sql) or math.isnan(dax):
        return False
    return relative_delta(sql, dax) <= epsilon
