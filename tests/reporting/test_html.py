from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from databricks_to_pbi.reporting.html import render_html, write_html
from databricks_to_pbi.reporting.report import (
    ObjectOutcome,
    SummaryStats,
    SyncReport,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor


def _r(needs_review: bool = False) -> SyncReport:
    return SyncReport(
        run_id="r-html",
        started_at=datetime(2026, 5, 26, tzinfo=UTC),
        finished_at=datetime(2026, 5, 26, tzinfo=UTC),
        target=TargetDescriptor(kind="pbip", target_id="/tmp/X"),
        mode="preview",
        delivery="pbip",
        summary=SummaryStats(created=1, needs_manual_review=1 if needs_review else 0),
        outcomes=[
            ObjectOutcome(
                object_kind="measure",
                name="Total Sales",
                action="created",
                source_refs=[],
                translation_method="rule" if not needs_review else "placeholder",
                warnings=["needs review"] if needs_review else [],
                needs_manual_review=needs_review,
                diff_preview=None,
            ),
        ],
        errors=[],
        fatal_error=None,
        source_inventory=[],
    )


def test_html_is_self_contained() -> None:
    html = render_html(_r())
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert "Total Sales" in html


def test_html_highlights_manual_review() -> None:
    html = render_html(_r(needs_review=True))
    assert "manual-review" in html or "Manual Review" in html


def test_write_html_creates_file(tmp_path: Path) -> None:
    p = write_html(_r(), root=tmp_path)
    assert p.exists()
    assert p.suffix == ".html"
