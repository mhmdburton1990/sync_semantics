from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.validation.models import (
    DimValue,
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)


def test_measure_validation_defaults() -> None:
    mv = MeasureValidation(name="total_revenue", status="skipped", skip_reason="placeholder")
    assert mv.dim_used is None
    assert mv.by_dim == []
    assert mv.scalar_matched is None


def test_validation_report_roundtrips_json() -> None:
    report = ValidationReport(
        model="sales",
        dataset_id="abc",
        workspace_id="ws1",
        epsilon=1e-6,
        ran_at=datetime(2026, 6, 3, tzinfo=UTC),
        results=[
            MeasureValidation(
                name="total_revenue",
                status="passed",
                dim_used="region",
                scalar_sql=100.0,
                scalar_dax=100.0,
                scalar_delta=0.0,
                scalar_matched=True,
                by_dim=[DimValue(key="EU", sql=60.0, dax=60.0, delta=0.0, matched=True)],
            )
        ],
        summary=ValidationSummary(passed=1, failed=0, skipped=0),
    )
    restored = ValidationReport.model_validate_json(report.model_dump_json())
    assert restored.results[0].by_dim[0].key == "EU"
    assert restored.summary.passed == 1
