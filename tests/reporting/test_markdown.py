from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from databricks_to_pbi.reporting.markdown import render_markdown, write_markdown
from databricks_to_pbi.reporting.report import (
    ObjectOutcome,
    SummaryStats,
    SyncReport,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor


def _report_with(outcomes: list[ObjectOutcome]) -> SyncReport:
    return SyncReport(
        run_id="r",
        started_at=datetime(2026, 5, 26, tzinfo=UTC),
        finished_at=datetime(2026, 5, 26, tzinfo=UTC),
        target=TargetDescriptor(kind="pbip", target_id="/tmp/X"),
        mode="preview",
        delivery="pbip",
        summary=SummaryStats(created=len([o for o in outcomes if o.action == "created"])),
        outcomes=outcomes,
        errors=[],
        fatal_error=None,
        source_inventory=[],
    )


def test_markdown_includes_summary_and_outcomes() -> None:
    r = _report_with([
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
    ])
    md = render_markdown(r)
    assert "# Sync Report" in md
    assert "Total Sales" in md
    assert "Created" in md or "created" in md


def test_markdown_flags_manual_review_section() -> None:
    r = _report_with([
        ObjectOutcome(
            object_kind="measure",
            name="Rolling Avg",
            action="created",
            source_refs=[],
            translation_method="placeholder",
            warnings=["Rolling Avg: SQL→DAX requires manual review"],
            needs_manual_review=True,
            diff_preview=None,
        ),
    ])
    md = render_markdown(r)
    assert "Manual Review" in md
    assert "Rolling Avg" in md


def test_write_markdown_creates_file(tmp_path: Path) -> None:
    r = _report_with([])
    p = write_markdown(r, root=tmp_path)
    assert p.exists()
    assert p.suffix == ".md"
