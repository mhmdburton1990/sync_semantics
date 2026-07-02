"""Self-contained, printable HTML migration confidence report.

Renders one shareable artifact from a finished SyncReport plus its optional
ValidationReport: a headline readiness score, translation method breakdown, and
per-measure validation outcomes with skip reasons.
"""

from __future__ import annotations

import html
from collections import Counter

from databricks_to_pbi.reporting.report import SyncReport
from databricks_to_pbi.validation.models import MeasureValidation, ValidationReport

__all__ = ["render_confidence_html"]


def _esc(v: object) -> str:
    return html.escape(str(v))


def _num(x: object) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.6g}"
    return _esc(x)


def _abs_delta(delta: float | None) -> float:
    return abs(delta) if delta is not None else -1.0


def _failure_summary(r: MeasureValidation) -> tuple[str, str]:
    """(Δ text, note) for a failed measure, surfacing the worst mismatch — the
    grand total if it diverged, otherwise the failing dimension value(s)."""
    candidates: list[tuple[str, float | None, float | None, float | None]] = []
    if r.scalar_matched is False:
        candidates.append(("grand total", r.scalar_sql, r.scalar_dax, r.scalar_delta))
    candidates += [
        (f"dim {d.key}", d.sql, d.dax, d.delta) for d in r.by_dim if not d.matched
    ]
    if not candidates:
        return "—", _esc(r.failed_side or r.skip_detail or "failed")
    label, sql, dax, delta = max(candidates, key=lambda c: _abs_delta(c[3]))
    note = f"{label}: SQL {_num(sql)} vs DAX {_num(dax)}"
    extra = len(candidates) - 1
    if extra:
        note += f" (+{extra} more)"
    return _num(delta), _esc(note)


def _readiness(validation: ValidationReport | None) -> str:
    if validation is None:
        return "Not validated"
    s = validation.summary
    total = s.passed + s.failed + s.skipped
    return f"{s.passed} of {total} measures validated within tolerance"


def _method_rows(report: SyncReport) -> str:
    counts: Counter[str] = Counter(
        o.translation_method or "n/a"
        for o in report.outcomes
        if o.object_kind == "measure"
    )
    if not counts:
        return "<tr><td colspan='2'>—</td></tr>"
    return "".join(
        f"<tr><td>{_esc(method)}</td><td>{count}</td></tr>"
        for method, count in sorted(counts.items())
    )


def _validation_rows(validation: ValidationReport | None) -> str:
    if validation is None:
        return "<tr><td colspan='4'>Not validated.</td></tr>"
    rows = []
    for r in validation.results:
        if r.status == "failed":
            delta_text, note = _failure_summary(r)
        elif r.status == "skipped":
            delta_text, note = "—", _esc(r.skip_category or r.skip_reason or "")
        else:  # passed
            delta_text, note = _num(r.scalar_delta), ""
        rows.append(
            f"<tr class='{_esc(r.status)}'><td>{_esc(r.name)}</td>"
            f"<td>{_esc(r.status)}</td>"
            f"<td>{delta_text}</td>"
            f"<td>{note}</td></tr>"
        )
    return "".join(rows)


def render_confidence_html(
    report: SyncReport, validation: ValidationReport | None,
) -> str:
    model = _esc(report.target_model_name or report.run_id)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Migration confidence — {model}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1b2b34; }}
  h1 {{ font-size: 1.4rem; }}
  .score {{ font-size: 1.6rem; font-weight: 700; margin: 1rem 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #d9e0e3; padding: 6px 10px; text-align: left; }}
  th {{ background: #f3f6f7; font-size: 0.75rem; text-transform: uppercase; }}
  tr.passed td {{ background: #ecfdf3; }}
  tr.failed td {{ background: #fdecec; }}
  tr.skipped td {{ background: #fef6e7; }}
</style></head><body>
<h1>Migration confidence report — {model}</h1>
<div>Run <code>{_esc(report.run_id)}</code> · delivery {_esc(report.delivery)} ·
state {_esc("published" if report.published_dataset_id else report.delivery)}</div>
<div class="score">{_esc(_readiness(validation))}</div>
<p>Measures created {_esc(report.summary.created)} · updated {_esc(report.summary.updated)} ·
needs manual review {_esc(report.summary.needs_manual_review)}</p>
<h2>Translation method</h2>
<table><thead><tr><th>Method</th><th>Measures</th></tr></thead>
<tbody>{_method_rows(report)}</tbody></table>
<h2>Validation</h2>
<table><thead><tr><th>Measure</th><th>Status</th><th>Δ</th><th>Note</th></tr></thead>
<tbody>{_validation_rows(validation)}</tbody></table>
</body></html>"""
