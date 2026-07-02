"""Translate a metric-view ``window:`` spec into DAX time intelligence.

Only the patterns that appear in real metric views are handled deterministically;
anything else returns None so the caller falls back to placeholder/LLM.
"""

from __future__ import annotations

import re

from databricks_to_pbi.ir import WindowClause

__all__ = ["translate_window"]

# "trailing 7 day inclusive" → (7, "day")
_TRAILING = re.compile(
    r"^\s*trailing\s+(\d+)\s+(day|month|quarter|year)s?\s+inclusive\s*$",
    re.IGNORECASE,
)
_UNIT_TO_DAX = {"day": "DAY", "month": "MONTH", "quarter": "QUARTER", "year": "YEAR"}


def translate_window(
    inner_dax: str, window: list[WindowClause], date_ref: str,
) -> str | None:
    """Wrap ``inner_dax`` in time-intelligence DAX for the given window spec, or
    None if the spec isn't a recognized pattern. ``date_ref`` is the DAX date
    column, e.g. ``'calendar'[date]``."""
    if not window:
        return None

    # YTD: cumulative over the date dim + "current" over a (year) dim.
    if len(window) == 2:
        ranges = {w.range.strip().lower() for w in window}
        if ranges == {"cumulative", "current"}:
            return f"CALCULATE({inner_dax}, DATESYTD({date_ref}))"
        return None

    if len(window) != 1:
        return None

    rng = window[0].range.strip()

    if rng.lower() == "cumulative":
        return (
            f"CALCULATE({inner_dax}, FILTER(ALL({date_ref}), "
            f"{date_ref} <= MAX({date_ref})))"
        )

    m = _TRAILING.match(rng)
    if m:
        n, unit = m.group(1), m.group(2).lower()
        return (
            f"CALCULATE({inner_dax}, DATESINPERIOD({date_ref}, "
            f"MAX({date_ref}), -{n}, {_UNIT_TO_DAX[unit]}))"
        )

    return None
