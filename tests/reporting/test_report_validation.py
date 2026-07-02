from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from databricks_to_pbi.reporting.report import SummaryStats, SyncReport, write_json
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.validation.models import (
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)


def _report(tmp_validation: ValidationReport | None) -> SyncReport:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return SyncReport(
        run_id="r1", started_at=now, finished_at=now,
        target=TargetDescriptor(kind="xmla", target_id="ws::"),
        target_model_name="sales", mode="apply", delivery="xmla_create",
        summary=SummaryStats(), outcomes=[], errors=[], fatal_error=None,
        source_inventory=[], validation=tmp_validation,
    )


def test_report_carries_validation_and_roundtrips(tmp_path: Path) -> None:
    vr = ValidationReport(
        model="sales", dataset_id="ds", workspace_id="ws", epsilon=1e-6,
        ran_at=datetime(2026, 6, 3, tzinfo=UTC),
        results=[MeasureValidation(name="rev", status="passed", scalar_matched=True)],
        summary=ValidationSummary(passed=1),
    )
    report = _report(vr)
    path = write_json(report, root=tmp_path)
    restored = SyncReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert restored.validation is not None
    assert restored.validation.summary.passed == 1


def test_validation_optional() -> None:
    assert _report(None).validation is None
