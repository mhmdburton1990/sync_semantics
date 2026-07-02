"""Ground-truth side: run MEASURE() queries against the metric view."""

from __future__ import annotations

from dataclasses import dataclass, field

from databricks_to_pbi.validation.dimension import GroupByDim, WarehouseLike

__all__ = ["OracleResult", "groupby_sql", "run_oracle", "scalar_sql"]


@dataclass(frozen=True, slots=True)
class OracleResult:
    scalar: float | None
    by_dim: dict[str | None, float | None] = field(default_factory=dict)


def scalar_sql(view: str, measure: str, where: str | None = None) -> str:
    clause = f" WHERE {where}" if where else ""
    return f"SELECT MEASURE(`{measure}`) AS m FROM {view}{clause} GROUP BY ALL"


def groupby_sql(view: str, measure: str, dim_ref: str, where: str | None = None) -> str:
    clause = f" WHERE {where}" if where else ""
    return (
        f"SELECT `{dim_ref}` AS k, MEASURE(`{measure}`) AS m "
        f"FROM {view}{clause} GROUP BY `{dim_ref}`"
    )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_key(v: object) -> str | None:
    return None if v is None else str(v)


def run_oracle(
    wc: WarehouseLike,
    *,
    view: str,
    measure: str,
    dim: GroupByDim | None,
    where: str | None = None,
) -> OracleResult:
    scalar_rows = wc.run_query(scalar_sql(view, measure, where))
    scalar = _to_float(scalar_rows[0][0]) if scalar_rows and scalar_rows[0] else None
    by_dim: dict[str | None, float | None] = {}
    if dim is not None:
        for row in wc.run_query(groupby_sql(view, measure, dim.sql_ref, where)):
            if not row:
                continue
            by_dim[_to_key(row[0])] = _to_float(row[1]) if len(row) > 1 else None
    return OracleResult(scalar=scalar, by_dim=by_dim)
