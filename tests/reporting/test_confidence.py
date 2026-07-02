from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.reporting.confidence import render_confidence_html
from databricks_to_pbi.reporting.report import SummaryStats, SyncReport
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.validation.models import (
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)


def _report() -> SyncReport:
    return SyncReport(
        run_id="r-1", started_at=datetime(2026, 6, 11, tzinfo=UTC),
        finished_at=datetime(2026, 6, 11, tzinfo=UTC),
        target=TargetDescriptor(kind="xmla", target_id="ws"),
        target_model_name="Sales", mode="apply", delivery="xmla_create",
        summary=SummaryStats(created=2, updated=0, needs_manual_review=0),
        outcomes=[], errors=[], fatal_error=None, source_inventory=[],
        published_dataset_id="ds",
    )


def _validation() -> ValidationReport:
    return ValidationReport(
        model="Sales", dataset_id="ds", workspace_id="ws", epsilon=1e-6,
        ran_at=datetime(2026, 6, 11, tzinfo=UTC),
        results=[
            MeasureValidation(name="total", status="passed", scalar_sql=10, scalar_dax=10),
            MeasureValidation(
                name="avg", status="skipped",
                skip_reason="sign in required", skip_category="credentials_not_signed_in",
            ),
        ],
        summary=ValidationSummary(passed=1, failed=0, skipped=1),
    )


def test_render_includes_readiness_score_and_model() -> None:
    rendered = render_confidence_html(_report(), _validation())
    assert "Sales" in rendered
    assert "1 of 2" in rendered  # readiness: passed / (passed+failed+skipped)
    assert "credentials_not_signed_in" in rendered
    assert rendered.lstrip().startswith("<!DOCTYPE html>")


def test_render_without_validation_states_not_run() -> None:
    rendered = render_confidence_html(_report(), None)
    assert "Not validated" in rendered


def test_render_shows_failure_delta_and_reason_for_dim_mismatch() -> None:
    from databricks_to_pbi.validation.models import DimValue

    validation = ValidationReport(
        model="Sales", dataset_id="ds", workspace_id="ws", epsilon=1e-6,
        ran_at=datetime(2026, 6, 11, tzinfo=UTC),
        results=[
            MeasureValidation(
                name="total_orders", status="failed",
                scalar_sql=100.0, scalar_dax=100.0, scalar_delta=0.0, scalar_matched=True,
                by_dim=[
                    DimValue(key="US", sql=60.0, dax=60.0, delta=0.0, matched=True),
                    DimValue(key="EU", sql=40.0, dax=33.0, delta=0.175, matched=False),
                ],
            ),
        ],
        summary=ValidationSummary(passed=0, failed=1, skipped=0),
    )
    rendered = render_confidence_html(_report(), validation)
    # The failing dimension + its diverging values must show — not a misleading 0.0/empty note.
    assert "EU" in rendered
    assert "33" in rendered       # the DAX value that diverged
    assert "0.175" in rendered    # the real delta


def test_render_shows_grand_total_failure() -> None:
    validation = ValidationReport(
        model="Sales", dataset_id="ds", workspace_id="ws", epsilon=1e-6,
        ran_at=datetime(2026, 6, 11, tzinfo=UTC),
        results=[
            MeasureValidation(
                name="total_sales", status="failed",
                scalar_sql=100.0, scalar_dax=80.0, scalar_delta=0.2,
                scalar_matched=False, by_dim=[],
            ),
        ],
        summary=ValidationSummary(passed=0, failed=1, skipped=0),
    )
    rendered = render_confidence_html(_report(), validation)
    assert "grand total" in rendered.lower()
    assert "0.2" in rendered
