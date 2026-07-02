"""Render a SyncReport as Markdown — for git-friendly attachment to PBIP/PBIT exports."""

from __future__ import annotations

from pathlib import Path

from databricks_to_pbi.reporting.report import SyncReport

__all__ = ["render_markdown", "write_markdown"]


def _validation_section(report: SyncReport) -> str:
    v = report.validation
    if v is None:
        return ""
    lines = [
        "",
        "## Validation",
        "",
        f"{v.summary.passed} passed · {v.summary.failed} failed · "
        f"{v.summary.skipped} skipped (epsilon={v.epsilon})",
        "",
        "| Measure | Status | Dim | SQL | DAX | Δ |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in v.results:
        lines.append(
            f"| {r.name} | {r.status} | {r.dim_used or '—'} | "
            f"{r.scalar_sql if r.scalar_sql is not None else '—'} | "
            f"{r.scalar_dax if r.scalar_dax is not None else '—'} | "
            f"{r.scalar_delta if r.scalar_delta is not None else '—'} |"
        )
    return "\n".join(lines)


def render_markdown(report: SyncReport) -> str:
    lines: list[str] = []
    lines.append("# Sync Report")
    lines.append(f"- **Run ID:** `{report.run_id}`")
    lines.append(f"- **Target:** {report.target.kind} → `{report.target.target_id}`")
    lines.append(f"- **Mode:** {report.mode}  /  **Delivery:** {report.delivery}")
    lines.append(f"- **Started:** {report.started_at.isoformat()}")
    lines.append(f"- **Finished:** {report.finished_at.isoformat()}")
    s = report.summary
    lines.append("")
    lines.append("## Summary")
    lines.append(
        f"- Created: {s.created} · Updated: {s.updated} · Unchanged: {s.unchanged} "
        f"· Renamed: {s.renamed} · Deleted: {s.deleted} · Skipped: {s.skipped}"
    )
    lines.append(f"- **Needs manual review:** {s.needs_manual_review}")
    lines.append("")
    manual = [o for o in report.outcomes if o.needs_manual_review]
    if manual:
        lines.append("## Manual Review")
        for o in manual:
            lines.append(
                f"- **{o.name}** ({o.object_kind}, {o.action}) — {', '.join(o.warnings) or '—'}"
            )
        lines.append("")
    lines.append("## Outcomes")
    lines.append("| Kind | Name | Action | Method | Warnings |")
    lines.append("|---|---|---|---|---|")
    for o in report.outcomes:
        warn = "; ".join(o.warnings) or ""
        lines.append(
            f"| {o.object_kind} | {o.name} | {o.action} | {o.translation_method or ''} | {warn} |"
        )
    if report.errors:
        lines.append("")
        lines.append("## Errors")
        for e in report.errors:
            lines.append(
                f"- `{e.code}` {e.message} ({'recoverable' if e.recoverable else 'fatal'})"
            )
    validation = _validation_section(report)
    if validation:
        lines.append(validation)
    return "\n".join(lines) + "\n"


def write_markdown(report: SyncReport, *, root: Path) -> Path:
    path = root / "reports" / f"{report.run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
