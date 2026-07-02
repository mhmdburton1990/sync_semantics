"""Categorize validation failures into actionable skip reasons.

A per-measure validation can fail on the source side (the metric-view
``MEASURE()`` query against the warehouse) or the DAX side (``executeQueries``
against the published model). ``classify_skip`` maps a caught exception to a
machine category, a short human-facing hint, and which side failed.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["FailedSide", "classify_skip", "skip_detail"]

FailedSide = Literal["source_sql", "dax", "setup"]

_CREDENTIALS_HINT = (
    "Open the dataset in Power BI Service → Settings → Data source "
    "credentials → sign in to Databricks, then re-validate."
)


def classify_skip(
    exc: Exception, *, side: FailedSide, dim: str | None,
) -> tuple[str, str, FailedSide]:
    msg = str(exc)
    low = msg.lower()
    if side == "source_sql":
        # All warehouse-side failures are uniform; exc detail is carried in skip_detail.
        return (
            "source_sql_error",
            "Source MEASURE() query failed on the warehouse — see detail.",
            "source_sql",
        )
    # side == "dax"
    if "executequeries" in low or "credential" in low:
        return ("credentials_not_signed_in", _CREDENTIALS_HINT, "dax")
    # Require the dimension to be implicated — either named explicitly, or a
    # clear "cannot find … column" pattern — so generic DAX errors that merely
    # mention "column" aren't mislabeled as a missing dimension.
    if dim is not None and (
        dim.lower() in low or ("cannot find" in low and "column" in low)
    ):
        return (
            "dim_not_found",
            f"Dimension '{dim}' was not found in the published model.",
            "dax",
        )
    return (
        "dax_error",
        "DAX query failed against the published model — see detail.",
        "dax",
    )


def skip_detail(exc: Exception, query: str | None) -> str:
    parts = [f"error: {exc}"]
    if query:
        parts.append(f"query: {query}")
    return "\n".join(parts)[:1500]
