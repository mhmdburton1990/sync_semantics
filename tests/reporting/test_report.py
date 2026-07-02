from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from databricks_to_pbi.reporting.report import (
    ErrorEntry,
    ObjectOutcome,
    SummaryStats,
    SyncReport,
    write_json,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor


def _report() -> SyncReport:
    return SyncReport(
        run_id="abc-123",
        started_at=datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 26, 10, 1, tzinfo=UTC),
        target=TargetDescriptor(kind="pbip", target_id="/tmp/SalesModel"),
        mode="preview",
        delivery="pbip",
        summary=SummaryStats(
            created=2, updated=0, unchanged=1, deleted=0,
            renamed=0, skipped=0, needs_manual_review=0,
        ),
        outcomes=[
            ObjectOutcome(
                object_kind="measure",
                name="Total Sales",
                action="created",
                source_refs=[],
                translation_method="rule",
                warnings=[],
                needs_manual_review=False,
                diff_preview=None,
            ),
        ],
        errors=[],
        fatal_error=None,
        source_inventory=[],
    )


def test_summary_counts_round_trip() -> None:
    r = _report()
    assert r.summary.created == 2


def test_write_json_emits_machine_readable(tmp_path: Path) -> None:
    r = _report()
    path = write_json(r, root=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "abc-123"
    assert payload["summary"]["created"] == 2


def test_error_entry_has_structured_payload() -> None:
    e = ErrorEntry(code="X", message="m", object="O", recoverable=True)
    assert e.recoverable is True
