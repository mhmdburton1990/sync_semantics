"""Render a SyncReport as a self-contained HTML page (no external CSS/JS)."""

from __future__ import annotations

from html import escape
from pathlib import Path

from databricks_to_pbi.reporting.report import SyncReport

__all__ = ["render_html", "write_html"]


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px;
       margin: 2em auto; padding: 0 1em; color: #222; }
table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 14px; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
th { background: #f5f5f5; }
.summary { display: flex; gap: 1em; flex-wrap: wrap; }
.summary .stat { background: #f0f4f8; padding: 0.5em 1em; border-radius: 4px; }
.manual-review { background: #fff7e6; border-left: 4px solid #f59e0b; padding: 1em; margin: 1em 0; }
.action-created { color: #2e7d32; }
.action-updated { color: #1565c0; }
.action-deleted { color: #c62828; }
.action-skipped { color: #888; }
.action-renamed { color: #6a1b9a; }
.action-unchanged { color: #555; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 10px;
        font-size: 12px; font-weight: 600; }
.chip-passed { background: #e8f5e9; color: #2e7d32; }
.chip-failed { background: #ffebee; color: #c62828; }
.chip-skipped { background: #fff8e1; color: #f59e0b; }
"""


def _validation_section_html(report: SyncReport) -> str:
    v = report.validation
    if v is None:
        return ""
    parts: list[str] = []
    parts.append("<h2>Validation</h2>")
    parts.append(
        f"<p>{v.summary.passed} passed · {v.summary.failed} failed · "
        f"{v.summary.skipped} skipped (epsilon={escape(str(v.epsilon))})</p>"
    )
    parts.append(
        "<table><tr><th>Measure</th><th>Status</th><th>Dim</th>"
        "<th>SQL</th><th>DAX</th><th>Δ</th></tr>"
    )
    for r in v.results:
        chip_class = f"chip chip-{r.status}"
        parts.append(
            f"<tr><td>{escape(r.name)}</td>"
            f"<td><span class='{chip_class}'>{escape(r.status)}</span></td>"
            f"<td>{escape(r.dim_used or '—')}</td>"
            f"<td>{escape(str(r.scalar_sql) if r.scalar_sql is not None else '—')}</td>"
            f"<td>{escape(str(r.scalar_dax) if r.scalar_dax is not None else '—')}</td>"
            f"<td>{escape(str(r.scalar_delta) if r.scalar_delta is not None else '—')}</td></tr>"
        )
    parts.append("</table>")
    return "\n".join(parts)


def render_html(report: SyncReport) -> str:
    s = report.summary
    manual = [o for o in report.outcomes if o.needs_manual_review]
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append("<html><head><meta charset='utf-8'>")
    parts.append(f"<title>Sync Report {escape(report.run_id)}</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body>")
    parts.append("<h1>Sync Report</h1>")
    parts.append("<p>")
    parts.append(f"<strong>Run:</strong> <code>{escape(report.run_id)}</code><br>")
    parts.append(
        f"<strong>Target:</strong> {escape(report.target.kind)} → "
        f"<code>{escape(report.target.target_id)}</code><br>"
    )
    parts.append(
        f"<strong>Mode/Delivery:</strong> {escape(report.mode)} / {escape(report.delivery)}<br>"
    )
    parts.append(f"<strong>Started:</strong> {escape(report.started_at.isoformat())}<br>")
    parts.append(f"<strong>Finished:</strong> {escape(report.finished_at.isoformat())}")
    parts.append("</p>")
    parts.append("<div class='summary'>")
    for label, val in [
        ("Created", s.created), ("Updated", s.updated), ("Unchanged", s.unchanged),
        ("Renamed", s.renamed), ("Deleted", s.deleted), ("Skipped", s.skipped),
        ("Manual Review", s.needs_manual_review),
    ]:
        parts.append(f"<div class='stat'><strong>{label}:</strong> {val}</div>")
    parts.append("</div>")
    if manual:
        parts.append("<div class='manual-review'><h2>Manual Review Required</h2><ul>")
        for o in manual:
            warn = "; ".join(o.warnings) or "no detail"
            parts.append(
                f"<li><strong>{escape(o.name)}</strong> "
                f"({escape(o.object_kind)}, {escape(o.action)}) — {escape(warn)}</li>"
            )
        parts.append("</ul></div>")
    parts.append("<h2>Outcomes</h2>")
    parts.append(
        "<table><tr><th>Kind</th><th>Name</th><th>Action</th><th>Method</th><th>Warnings</th></tr>"
    )
    for o in report.outcomes:
        warn = escape("; ".join(o.warnings))
        parts.append(
            f"<tr><td>{escape(o.object_kind)}</td><td>{escape(o.name)}</td>"
            f"<td class='action-{o.action}'>{escape(o.action)}</td>"
            f"<td>{escape(o.translation_method or '')}</td>"
            f"<td>{warn}</td></tr>"
        )
    parts.append("</table>")
    validation = _validation_section_html(report)
    if validation:
        parts.append(validation)
    parts.append("</body></html>")
    return "\n".join(parts)


def write_html(report: SyncReport, *, root: Path) -> Path:
    path = root / "reports" / f"{report.run_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path
