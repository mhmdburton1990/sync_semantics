"""Orchestrate per-measure validation into a ValidationReport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from databricks_to_pbi.ir import DatabricksSemanticIR, Measure
from databricks_to_pbi.validation.compare import DEFAULT_EPSILON, is_match, relative_delta
from databricks_to_pbi.validation.dimension import GroupByDim, WarehouseLike
from databricks_to_pbi.validation.models import (
    DimValue,
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)
from databricks_to_pbi.validation.oracle import OracleResult, run_oracle, scalar_sql
from databricks_to_pbi.validation.skips import classify_skip, skip_detail
from databricks_to_pbi.validation.timeframe import DateWindow, dax_predicate, sql_where

__all__ = ["DaxClientLike", "ValidationInputs", "validate_model"]


class DaxClientLike(Protocol):
    def scalar(self, measure: str, date_filter: str | None = None) -> float | None: ...
    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
        date_filter: str | None = None,
    ) -> dict[str | None, float | None]: ...


OracleFn = Callable[..., OracleResult]


@dataclass(frozen=True, slots=True)
class ValidationInputs:
    ir: DatabricksSemanticIR
    methods: dict[str, str]
    wc: WarehouseLike
    dax_client_for: Callable[[str], DaxClientLike]
    model: str
    dataset_id: str
    workspace_id: str
    ran_at: datetime
    epsilon: float = DEFAULT_EPSILON
    dim_override: GroupByDim | None = None
    oracle_fn: OracleFn = run_oracle
    date_window: DateWindow | None = None


def _delta(sql: float | None, dax: float | None) -> float | None:
    if sql is None or dax is None:
        return None
    return relative_delta(sql, dax)


def _compare_by_dim(
    sql: dict[str | None, float | None],
    dax: dict[str | None, float | None],
    *,
    epsilon: float,
) -> list[DimValue]:
    rows: list[DimValue] = []
    def _sort_key(k: str | None) -> tuple[bool, str]:
        return (k is None, k if k is not None else "")

    for key in sorted(sql.keys() | dax.keys(), key=_sort_key):
        s = sql.get(key)
        d = dax.get(key)
        rows.append(
            DimValue(
                key=key, sql=s, dax=d, delta=_delta(s, d),
                matched=is_match(s, d, epsilon=epsilon),
            )
        )
    return rows


def _validate_one(
    inputs: ValidationInputs, measure: Measure, dim: GroupByDim | None,
) -> MeasureValidation:
    measure_name = measure.name
    method = inputs.methods.get(measure_name, "placeholder")
    if method == "placeholder":
        return MeasureValidation(
            name=measure_name, status="skipped",
            skip_reason="no translated DAX to validate (placeholder)",
            skip_category="placeholder", failed_side="setup",
        )
    if measure.source.kind != "metric_view":
        return MeasureValidation(
            name=measure_name, status="skipped",
            skip_reason="only metric view measures can be validated",
            skip_category="non_metric_view", failed_side="setup",
        )
    view = measure.source.fully_qualified_name
    client = inputs.dax_client_for(measure_name)
    window = inputs.date_window
    where = sql_where(window) if window is not None else None
    date_filter = dax_predicate(window) if window is not None else None
    dim_ref = dim.sql_ref if dim is not None else None

    try:
        oracle = inputs.oracle_fn(
            inputs.wc, view=view, measure=measure_name, dim=dim, where=where,
        )
    except Exception as exc:  # source-side (warehouse) failure
        cat, hint, side = classify_skip(exc, side="source_sql", dim=dim_ref)
        return MeasureValidation(
            name=measure_name, status="skipped", skip_reason=hint,
            skip_category=cat, failed_side=side,
            skip_detail=skip_detail(exc, scalar_sql(view, measure_name, where)),
        )

    try:
        scalar_dax = client.scalar(measure_name, date_filter=date_filter)
        dax_by_dim = (
            client.by_dim(
                measure_name, dim.dax_table, dim.dax_column, date_filter=date_filter,
            )
            if dim is not None else {}
        )
    except Exception as exc:  # DAX-side (executeQueries) failure
        cat, hint, side = classify_skip(exc, side="dax", dim=dim_ref)
        return MeasureValidation(
            name=measure_name, status="skipped", skip_reason=hint,
            skip_category=cat, failed_side=side,
            skip_detail=skip_detail(exc, None),
        )

    scalar_matched = is_match(oracle.scalar, scalar_dax, epsilon=inputs.epsilon)
    by_dim = (
        _compare_by_dim(oracle.by_dim, dax_by_dim, epsilon=inputs.epsilon)
        if dim is not None else []
    )
    status: Literal["passed", "failed"] = (
        "passed" if scalar_matched and all(d.matched for d in by_dim) else "failed"
    )
    return MeasureValidation(
        name=measure_name,
        status=status,
        dim_used=dim.sql_ref if dim is not None else None,
        scalar_sql=oracle.scalar,
        scalar_dax=scalar_dax,
        scalar_delta=_delta(oracle.scalar, scalar_dax),
        scalar_matched=scalar_matched,
        by_dim=by_dim,
    )


def validate_model(inputs: ValidationInputs) -> ValidationReport:
    dim = inputs.dim_override
    results = [_validate_one(inputs, m, dim) for m in inputs.ir.measures]
    summary = ValidationSummary(
        passed=sum(1 for r in results if r.status == "passed"),
        failed=sum(1 for r in results if r.status == "failed"),
        skipped=sum(1 for r in results if r.status == "skipped"),
    )
    return ValidationReport(
        model=inputs.model,
        dataset_id=inputs.dataset_id,
        workspace_id=inputs.workspace_id,
        epsilon=inputs.epsilon,
        ran_at=inputs.ran_at,
        results=results,
        summary=summary,
    )
