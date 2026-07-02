import { useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { api, ApiClientError } from '../api'
import { useSelectedCatalog, useSelectedSchema } from '../catalog'
import { useRunDetail } from '../lib/queryClient'
import { useWarehouseId } from '../warehouse'
import { ValidationRunner } from '../components/ValidationRunner'
import { PageHeader } from './SourcesPicker'

const TIMEFRAME_LABELS: Record<string, string> = {
  all: 'All data',
  day: 'Last day',
  week: 'Last week',
  month: 'Last month',
  quarter: 'Last quarter',
  year: 'Last year',
}


export function HistoryDetail(): JSX.Element {
  const { runId } = useParams({ from: '/history/$runId' })
  const wh = useWarehouseId()
  const catalog = useSelectedCatalog()
  const schema = useSelectedSchema()
  const detail = useRunDetail(runId)
  const [reportErr, setReportErr] = useState<string | null>(null)

  async function openReport(reportRunId: string): Promise<void> {
    setReportErr(null)
    try {
      const html = await api.getReportHtml(reportRunId)
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      setReportErr(e instanceof ApiClientError ? e.envelope.message : String(e))
    }
  }

  if (!wh || !catalog || !schema) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Run detail" />
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          {!wh
            ? 'Pick a SQL warehouse above to view this run.'
            : 'Pick a source catalog + schema (on the Sources tab) — run history is scoped to that namespace.'}
        </div>
      </div>
    )
  }

  if (detail.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Run detail" />
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          Loading…
        </div>
      </div>
    )
  }
  if (detail.error || !detail.data) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="History" title="Run detail" />
        <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700 shadow-card">
          Run not found.
        </div>
      </div>
    )
  }

  const d = detail.data
  const measures = d.report.outcomes.filter((o) => o.object_kind === 'measure')
  const byMethod: Record<string, number> = {}
  for (const m of measures) {
    const k = m.translation_method ?? 'n/a'
    byMethod[k] = (byMethod[k] ?? 0) + 1
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="History"
        title={d.model_name ?? d.run_id}
        subtitle={`${d.state} · ${new Date(d.created_at).toLocaleString()}${
          d.run_by ? ` · ${d.run_by}` : ''
        }`}
      />

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void openReport(d.run_id)}
          className="inline-flex items-center rounded-md bg-databricks-ink px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-ink/90"
        >
          Open report
        </button>
        {reportErr && <span className="text-xs text-red-700">{reportErr}</span>}
      </div>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white p-5 shadow-card">
        <div className="text-sm font-semibold text-databricks-ink">Translation</div>
        <div className="mt-2 text-xs text-slate-600">
          created={d.report.summary.created} · updated={d.report.summary.updated} ·
          needs_review={d.report.summary.needs_manual_review}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(byMethod).map(([method, n]) => (
            <span
              key={method}
              className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700"
            >
              {method}: {n}
            </span>
          ))}
        </div>
      </section>

      {d.validation && (
        <div className="text-xs text-slate-500">
          Last validated with — Dimension:{' '}
          <span className="font-medium text-slate-700">{d.val_dimension ?? 'Grand total only'}</span>
          {' · '}Timeframe:{' '}
          <span className="font-medium text-slate-700">
            {d.val_timeframe ? (TIMEFRAME_LABELS[d.val_timeframe] ?? d.val_timeframe) : 'All data'}
          </span>
        </div>
      )}

      {d.dataset_id ? (
        <ValidationRunner
          sources={d.sources}
          modelName={d.model_name ?? ''}
          datasetId={d.dataset_id}
          workspaceId={d.workspace_id ?? ''}
          runId={d.run_id}
          initialResults={d.validation?.results}
          initialSummary={d.validation?.summary}
        />
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          This run wasn&apos;t published to Power BI, so there&apos;s no dataset to validate against.
        </div>
      )}
    </div>
  )
}
