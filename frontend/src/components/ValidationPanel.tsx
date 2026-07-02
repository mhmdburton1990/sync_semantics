import { Fragment } from 'react'
import type { MeasureValidation, ValidationSummary } from '../types'

export interface ValidationPanelProps {
  results: MeasureValidation[]
  summary: ValidationSummary
  running?: boolean
  total?: number
  current?: string | null
}

function fmt(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return '—'
  // Show up to 4 significant digits
  return parseFloat(x.toPrecision(4)).toString()
}

function StatusChip(props: { status: MeasureValidation['status'] }): JSX.Element {
  const cls =
    props.status === 'passed'
      ? 'bg-emerald-100 text-emerald-800'
      : props.status === 'failed'
      ? 'bg-red-100 text-red-800'
      : 'bg-amber-100 text-amber-800'
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${cls}`}>
      {props.status}
    </span>
  )
}

export function ValidationPanel(props: ValidationPanelProps): JSX.Element {
  const { results, summary, running = false, total, current } = props

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
      {/* Header */}
      <div className="border-b border-slate-200 bg-slate-50/60 px-5 py-3">
        <div className="flex items-baseline justify-between">
          <div className="text-sm font-semibold text-databricks-ink">Validation</div>
          <div className="text-xs text-slate-500">
            {running && (
              <span className="mr-2 text-databricks-ink">
                {current
                  ? `Validating ${current} (${results.length + 1} of ${total ?? results.length})…`
                  : 'Preparing validation… (the SQL warehouse may be starting)'}
              </span>
            )}
            <span className="font-semibold text-emerald-700">{summary.passed} passed</span>
            {' · '}
            <span className="font-semibold text-red-700">{summary.failed} failed</span>
            {' · '}
            <span className="font-semibold text-amber-700">{summary.skipped} skipped</span>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-white text-left text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-5 py-2">Measure</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Dim</th>
              <th className="px-3 py-2 text-right">SQL</th>
              <th className="px-3 py-2 text-right">DAX</th>
              <th className="px-3 py-2 text-right">Δ</th>
              <th className="px-3 py-2">Note</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <Fragment key={r.name}>
                <tr className="border-t border-slate-100">
                  <td className="px-5 py-2 font-mono text-sm font-medium text-databricks-ink">
                    {r.name}
                  </td>
                  <td className="px-3 py-2">
                    <StatusChip status={r.status} />
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {r.by_dim.length > 0 ? 'total' : (r.dim_used ?? '—')}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-700">
                    {fmt(r.scalar_sql)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-700">
                    {fmt(r.scalar_dax)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-700">
                    {fmt(r.scalar_delta)}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {r.skip_reason && (
                      <div className="flex items-start gap-1.5">
                        {r.failed_side && (
                          <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                            {r.failed_side === 'source_sql' ? 'source' : r.failed_side}
                          </span>
                        )}
                        <span>{r.skip_reason}</span>
                      </div>
                    )}
                    {r.skip_detail && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[11px] text-slate-400">
                          detail
                        </summary>
                        <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-[11px] text-slate-600">
                          {r.skip_detail}
                        </pre>
                      </details>
                    )}
                  </td>
                </tr>
                {/* Per-dimension breakdown (one row per group-by key). */}
                {r.by_dim.map((dv) => (
                  <tr key={`${r.name}:${dv.key ?? '∅'}`} className="bg-slate-50/40">
                    <td className="px-5 py-1 pl-10 text-xs text-slate-400">↳</td>
                    <td className="px-3 py-1 text-xs">
                      {dv.matched
                        ? <span className="text-emerald-600">✓</span>
                        : <span className="font-semibold text-red-600">✗</span>}
                    </td>
                    <td className="px-3 py-1 text-xs text-slate-600">{dv.key ?? '(blank)'}</td>
                    <td className="px-3 py-1 text-right font-mono text-xs text-slate-600">
                      {fmt(dv.sql)}
                    </td>
                    <td className="px-3 py-1 text-right font-mono text-xs text-slate-600">
                      {fmt(dv.dax)}
                    </td>
                    <td className="px-3 py-1 text-right font-mono text-xs text-slate-600">
                      {fmt(dv.delta)}
                    </td>
                    <td />
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
