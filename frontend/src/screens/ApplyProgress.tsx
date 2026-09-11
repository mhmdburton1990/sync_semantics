import { useMemo } from 'react'
import { useSse } from '../lib/sse'
import { useUrlList, useUrlParam } from '../lib/url-state'
import type { DeliveryKind, SyncReport, SyncSourceRef } from '../types'
import { ArrowFlow, DatabricksMark, PowerBiMark } from '../components/BrandMarks'
import { PageHeader } from './SourcesPicker'


export function ApplyProgress(): JSX.Element {
  const [mvs] = useUrlList('mv')
  const [dashes] = useUrlList('dash')
  const [spaces] = useUrlList('space')
  const [exclude] = useUrlList('exclude')
  const [kind] = useUrlParam<DeliveryKind>('kind', 'xmla')
  const [targetId] = useUrlParam<string>('target_id', '')
  const [modelName] = useUrlParam<string>('model_name', '')
  const [xmlaMerge] = useUrlParam<string>('xmla_merge', 'false')
  // Wire format set by Preview: "table1:dual,table2:directQuery,...".
  const [storageModesRaw] = useUrlParam<string>('storage_modes', '')

  const body = useMemo(() => {
    const sources: SyncSourceRef[] = [
      ...mvs.map((id) => ({ kind: 'metric_view' as const, id })),
      ...dashes.map((id) => ({ kind: 'dashboard' as const, id })),
      ...spaces.map((id) => ({ kind: 'genie_space' as const, id })),
    ]
    const storage_modes: Record<string, string> = {}
    for (const pair of storageModesRaw.split(',')) {
      const [t, m] = pair.split(':')
      if (t && (m === 'import' || m === 'direct_query' || m === 'dual')) {
        storage_modes[t] = m
      }
    }
    return {
      sources,
      target: { kind, target_id: targetId },
      model_name: modelName,
      xmla_merge: xmlaMerge === 'true',
      storage_modes,
      exclude_measures: exclude,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mvs.join(','), dashes.join(','), spaces.join(','), exclude.join(','), kind, targetId, modelName, xmlaMerge, storageModesRaw])

  const { events, done, error } = useSse(
    targetId && modelName ? '/api/sync/apply' : null,
    body,
  )
  const finalEvent = events.find((e) => e.name === 'done')
  // Defensive: never let a malformed/partial done payload throw during render
  // (an uncaught throw here trips the app error boundary and blanks the page).
  let report: SyncReport | null = null
  if (finalEvent) {
    try {
      report = JSON.parse(finalEvent.data) as SyncReport
    } catch {
      report = null
    }
  }

  const canValidate =
    done &&
    !!report?.summary &&
    (report.delivery === 'xmla_create' || report.delivery === 'xmla_merge') &&
    !!report.published_dataset_id

  let validateHref: string | null = null
  if (canValidate && report?.published_dataset_id) {
    const p = new URLSearchParams(window.location.search)
    p.set('dataset_id', report.published_dataset_id)
    if (report.run_id) p.set('run_id', report.run_id)
    p.delete('vjob') // start a fresh validation context, not a stale resume
    validateHref = `/validate?${p.toString()}`
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Applying"
        title={modelName || 'Model'}
        subtitle={
          done
            ? 'Apply complete.'
            : 'Streaming engine progress live — files are being written.'
        }
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-card">
          <div className="font-medium text-red-800">Error</div>
          <div>{error}</div>
        </div>
      )}

      {!done && !error && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
          <div className="flex items-center justify-center gap-3">
            <DatabricksMark className="h-10 w-10 animate-pulse" />
            <ArrowFlow className="h-3 w-12 animate-pulse text-databricks-red" />
            <PowerBiMark className="h-10 w-10 animate-pulse" />
          </div>
          <div className="mt-3 text-center text-sm font-medium text-databricks-ink">
            {kind === 'xmla' ? 'Pushing the model' : 'Generating the model'}
          </div>
        </div>
      )}

      {events.length > 0 && (
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="border-b border-slate-200 bg-slate-50/60 px-5 py-3 text-sm font-semibold text-databricks-ink">
            Event stream
          </div>
          <ul className="divide-y divide-slate-100 text-sm">
            {events.map((e, i) => (
              <li key={i} className="flex items-baseline gap-3 px-5 py-2 font-mono text-xs">
                <span
                  className={[
                    'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
                    e.name === 'done'
                      ? 'bg-emerald-100 text-emerald-800'
                      : e.name === 'start'
                      ? 'bg-blue-100 text-blue-800'
                      : 'bg-slate-100 text-slate-700',
                  ].join(' ')}
                >
                  {e.name}
                </span>
                <span className="truncate text-slate-700">{e.data.slice(0, 200)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {done && !report && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 shadow-card">
          Apply finished, but the result payload could not be read. Check{' '}
          <a href="/history" className="underline underline-offset-4">History</a> for this run.
        </div>
      )}

      {done && report?.summary && (
        <section className="overflow-hidden rounded-xl border border-databricks-mint/40 bg-gradient-to-br from-emerald-50 to-white p-5 shadow-card">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-full bg-databricks-mint text-white">
              <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M16.7 5.3a1 1 0 0 0-1.4 0L8 12.6 4.7 9.3a1 1 0 1 0-1.4 1.4l4 4a1 1 0 0 0 1.4 0l8-8a1 1 0 0 0 0-1.4Z"
                />
              </svg>
            </div>
            <div>
              <div className="text-base font-semibold text-databricks-ink">Apply complete</div>
              <div className="text-xs text-slate-600">
                created={report.summary.created} · updated={report.summary.updated} ·
                {' '}needs_review={report.summary.needs_manual_review}
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            {(kind === 'pbip' || kind === 'pbit') && (
              <a
                href={`/api/sync/download?model=${encodeURIComponent(modelName)}`}
                className="inline-flex items-center gap-2 rounded-md bg-databricks-ink px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-ink/90"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M10 2a1 1 0 0 1 1 1v8.6l2.3-2.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L9 11.6V3a1 1 0 0 1 1-1Zm-7 14a1 1 0 1 1 0 2h14a1 1 0 1 1 0 2H3a1 1 0 0 1 0-2Z"
                  />
                </svg>
                Download {kind === 'pbit' ? '.pbit' : '.zip'}
              </a>
            )}
            <a
              href="/"
              className="inline-flex items-center gap-2 rounded-md bg-databricks-red px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-red/90"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M10 2.6a1 1 0 0 1 .7.3l7 7a1 1 0 0 1-1.4 1.4L16 11v6a1 1 0 0 1-1 1h-3v-4H8v4H5a1 1 0 0 1-1-1v-6l-.3.3a1 1 0 0 1-1.4-1.4l7-7a1 1 0 0 1 .7-.3Z"
                />
              </svg>
              Sync new model
            </a>
            <a
              href="/history"
              className="text-sm text-databricks-ink underline-offset-4 hover:underline"
            >
              See in history →
            </a>
          </div>
        </section>
      )}

      {validateHref && (
        <a
          href={validateHref}
          className="inline-flex items-center gap-2 rounded-md bg-databricks-ink px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-ink/90"
        >
          Validate model →
        </a>
      )}
    </div>
  )
}
