import { Link } from '@tanstack/react-router'
import { useSelectedCatalog, useSelectedSchema } from '../catalog'
import { useHistory } from '../lib/queryClient'
import { useWarehouseId } from '../warehouse'
import { PageHeader } from './SourcesPicker'


function ValidationStatusChip(props: { status: string }): JSX.Element {
  const map: Record<string, string> = {
    passed: 'bg-emerald-100 text-emerald-800',
    failed: 'bg-red-100 text-red-800',
    partial: 'bg-amber-100 text-amber-800',
    not_run: 'bg-slate-100 text-slate-500',
  }
  const cls = map[props.status] ?? 'bg-slate-100 text-slate-500'
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${cls}`}>
      {props.status === 'not_run' ? 'not run' : props.status}
    </span>
  )
}

function StateBadge(props: { state: string }): JSX.Element {
  const map: Record<string, string> = {
    published: 'bg-emerald-100 text-emerald-800',
    exported: 'bg-blue-100 text-blue-800',
    failed: 'bg-red-100 text-red-800',
    published_failed: 'bg-red-100 text-red-800',
  }
  const cls = map[props.state] ?? 'bg-slate-100 text-slate-600'
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {props.state}
    </span>
  )
}


export function History(): JSX.Element {
  const wh = useWarehouseId()
  const catalog = useSelectedCatalog()
  const schema = useSelectedSchema()
  const history = useHistory()

  if (!wh || !catalog || !schema) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Past runs" />
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          {!wh
            ? 'Pick a SQL warehouse above to view your migration history.'
            : 'Pick a source catalog + schema (on the Sources tab) — run history is scoped to that namespace.'}
        </div>
      </div>
    )
  }

  if (history.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Past runs" />
        <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          <span className="h-2 w-2 animate-pulse rounded-full bg-databricks-red" />
          Loading…
        </div>
      </div>
    )
  }
  if (history.error) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Past runs" />
        <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700 shadow-card">
          Failed to load history.
        </div>
      </div>
    )
  }
  const items = history.data ?? []
  if (items.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Past runs" />
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-card">
          <div className="text-sm text-slate-500">No runs yet.</div>
          <div className="mt-1 text-xs text-slate-400">
            Once you Apply a model, every run shows up here.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="History"
        title="Past runs"
        subtitle={`${items.length} run${items.length === 1 ? '' : 's'} on record`}
      />
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/60 text-left text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-5 py-3">Run</th>
              <th className="px-3 py-3">When</th>
              <th className="px-3 py-3">Model</th>
              <th className="px-3 py-3">State</th>
              <th className="px-3 py-3">Validation</th>
              <th className="px-3 py-3">Created</th>
              <th className="px-3 py-3">Updated</th>
              <th className="px-3 py-3">Needs review</th>
            </tr>
          </thead>
          <tbody>
            {items.map((h) => (
              <tr key={h.run_id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-5 py-2 font-mono text-xs">
                  <Link
                    to="/history/$runId"
                    params={{ runId: h.run_id }}
                    className="text-databricks-ink underline-offset-4 hover:underline"
                  >
                    {h.run_id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="px-3 py-2 text-slate-700">
                  {new Date(h.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2 text-slate-700">{h.model_name ?? '—'}</td>
                <td className="px-3 py-2">
                  <StateBadge state={h.state} />
                </td>
                <td className="px-3 py-2">
                  <ValidationStatusChip status={h.validation_status} />
                </td>
                <td className="px-3 py-2 text-emerald-700">{h.summary_created}</td>
                <td className="px-3 py-2 text-blue-700">{h.summary_updated}</td>
                <td
                  className={`px-3 py-2 ${
                    h.summary_needs_manual_review > 0
                      ? 'font-medium text-amber-700'
                      : 'text-slate-500'
                  }`}
                >
                  {h.summary_needs_manual_review}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
