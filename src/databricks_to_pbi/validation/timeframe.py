"""Detect a date column and compute a date window for time-bounded validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.validation.dimension import WarehouseLike

__all__ = [
    "DateWindow",
    "Timeframe",
    "candidate_date_columns",
    "compute_window",
    "dax_predicate",
    "detect_date_column",
    "sql_where",
]

Timeframe = Literal["all", "day", "week", "month", "quarter", "year"]
_WINDOW_DAYS: dict[str, int] = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
_DATE_PREFIXES = ("date", "timestamp")


@dataclass(frozen=True, slots=True)
class DateWindow:
    sql_column: str   # column name in the metric view (for the SQL WHERE)
    dax_table: str    # PBI table that owns the date column
    dax_column: str   # PBI column name (for the DAX filter)
    start: date       # inclusive
    end: date         # inclusive


def _resolve_dim_column(
    ir: DatabricksSemanticIR, expression: str,
) -> tuple[str, str] | None:
    """Resolve a dimension's expression to the (pbi_table, pbi_column) it maps
    to. Qualified refs (``source.calendar.date`` / ``orders.o_orderdate``) take
    their last two segments; a bare column is matched against the table that
    actually has it (host first)."""
    expr = expression.replace("source.", "").strip()
    if "." in expr:
        parts = expr.split(".")
        return parts[-2], parts[-1]
    for t in ir.tables:  # tables[0] is the host/source; first match wins
        if any(c.name == expr for c in t.columns):
            return t.name, expr
    return None


def candidate_date_columns(ir: DatabricksSemanticIR) -> list[tuple[str, str, str]]:
    """Date/timestamp candidates as (sql_column, pbi_table, pbi_column), best-first.

    The SQL side queries the metric VIEW, which only exposes its DIMENSIONS as
    columns (not the underlying physical columns) — so candidates are the view's
    date-typed *dimensions*: ``sql_column`` is the dimension name (queryable on
    the view) and ``pbi_table``/``pbi_column`` are the physical column it maps to
    (for the DAX relationship filter).

    A date filter must constrain measures the same way in SQL (via joins) and in
    DAX (via relationships). Filtering a leaf column doesn't propagate up to a
    parent-grain measure in DAX, so we prefer a dimension whose column sits on a
    PARENT table (the ``to_table`` / "one" side of a relationship).
    """
    type_of = {
        (t.name, c.name): (c.data_type or "")
        for t in ir.tables
        for c in t.columns
    }
    parent_tables = {r.to_table for r in ir.relationships}
    cands: list[tuple[str, str, str]] = []
    for d in ir.dimensions:
        resolved = _resolve_dim_column(ir, d.expression)
        if resolved is None:
            continue
        table, col = resolved
        if type_of.get((table, col), "").strip().lower().startswith(_DATE_PREFIXES):
            cands.append((d.name, table, col))
    # Higher sorts first: a column on a parent table.
    cands.sort(key=lambda dc: dc[1] in parent_tables, reverse=True)
    return cands


def detect_date_column(ir: DatabricksSemanticIR) -> tuple[str, str, str] | None:
    """Return the single best (view_column, pbi_table, pbi_column) date column,
    or None. See ``candidate_date_columns`` for the ordering rationale."""
    cands = candidate_date_columns(ir)
    return cands[0] if cands else None


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_window(
    wc: WarehouseLike,
    ir: DatabricksSemanticIR,
    timeframe: Timeframe,
    date_override: tuple[str, str] | None = None,
) -> DateWindow | None:
    """Compute [max(date) - window, max(date)] for a bounded timeframe; None for
    'all' or when there is no usable date column / no max date.

    ``date_override`` is (pbi_table, pbi_column); when it matches a candidate it
    is used instead of the auto-detected best column. An unmatched override falls
    back to auto-detect."""
    if timeframe == "all" or not ir.sources:
        return None
    found: tuple[str, str, str] | None = None
    if date_override is not None:
        table, column = date_override
        found = next(
            (c for c in candidate_date_columns(ir) if c[1] == table and c[2] == column),
            None,
        )
    if found is None:
        found = detect_date_column(ir)
    if found is None:
        return None
    sql_col, dax_table, dax_col = found
    view = ir.sources[0].fully_qualified_name
    rows = wc.run_query(f"SELECT MAX(`{sql_col}`) FROM {view}")
    max_d = _to_date(rows[0][0]) if rows and rows[0] else None
    if max_d is None:
        return None
    start = max_d - timedelta(days=_WINDOW_DAYS[timeframe])
    return DateWindow(sql_column=sql_col, dax_table=dax_table, dax_column=dax_col,
                      start=start, end=max_d)


def sql_where(window: DateWindow) -> str:
    return (
        f"`{window.sql_column}` >= DATE '{window.start.isoformat()}' "
        f"AND `{window.sql_column}` <= DATE '{window.end.isoformat()}'"
    )


def dax_predicate(window: DateWindow) -> str:
    col = f"'{window.dax_table}'[{window.dax_column}]"
    s, e = window.start, window.end
    return (
        f"{col} >= DATE({s.year},{s.month},{s.day}) "
        f"&& {col} <= DATE({e.year},{e.month},{e.day})"
    )
