"""Candidate group-by dimensions for the per-slice comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from databricks_to_pbi.ir import DatabricksSemanticIR

__all__ = ["GroupByDim", "WarehouseLike", "candidate_dims"]


class WarehouseLike(Protocol):
    def run_query(self, statement: str) -> list[list[object]]: ...


@dataclass(frozen=True, slots=True)
class GroupByDim:
    sql_ref: str       # dimension name valid in the metric-view GROUP BY
    dax_table: str     # PBI table that owns the mapped column
    dax_column: str    # PBI column name (lowercase) for SUMMARIZECOLUMNS


def _column_owner(ir: DatabricksSemanticIR, column_name: str) -> str | None:
    owners = [t.name for t in ir.tables if any(c.name == column_name for c in t.columns)]
    return owners[0] if len(owners) == 1 else None


def _resolve_column(
    ir: DatabricksSemanticIR, raw: str,
) -> tuple[str, str] | None:
    """Resolve an underlying-column reference to (table, column).

    Metric-view dimensions express their underlying column either as a bare
    name (``l_returnflag``) or as a join-qualified path (``orders.o_orderstatus``,
    ``orders.customer.c_name``, ``orders.calendar.year``). For a path the last
    segment is the column and the segment before it is the owning table; for a
    bare name we find the unique table that has it. Returns None if it can't be
    resolved to a real (table, column) in the IR.
    """
    parts = raw.split(".")
    col = parts[-1]
    table_names = {t.name for t in ir.tables}
    table = parts[-2] if len(parts) >= 2 and parts[-2] in table_names else _column_owner(ir, col)
    if table is None:
        return None
    tbl = next((t for t in ir.tables if t.name == table), None)
    if tbl is None or not any(c.name == col for c in tbl.columns):
        return None
    return table, col


def candidate_dims(ir: DatabricksSemanticIR) -> list[GroupByDim]:
    """Dimensions that resolve to a single column on exactly one table.

    Handles both bare and join-qualified underlying-column references, so a
    dimension like ``o_orderstatus`` (underlying ``orders.o_orderstatus``) or
    ``order_year`` (underlying ``orders.calendar.year``) is included.
    """
    out: list[GroupByDim] = []
    for d in ir.dimensions:
        if len(d.underlying_columns) != 1:
            continue
        resolved = _resolve_column(ir, d.underlying_columns[0])
        if resolved is None:
            continue
        table, col = resolved
        out.append(GroupByDim(sql_ref=d.name, dax_table=table, dax_column=col))
    return out


