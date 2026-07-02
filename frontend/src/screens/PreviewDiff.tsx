import { useEffect, useState } from 'react'
import { ApiClientError, useSyncPreview } from '../lib/queryClient'
import { useUrlList, useUrlParam } from '../lib/url-state'
import type {
  DeliveryKind,
  SyncOutcome,
  SyncReport,
  SyncSourceRef,
  TableInfo,
} from '../types'
import { ArrowFlow, DatabricksMark, PowerBiMark } from '../components/BrandMarks'
import { PageHeader } from './SourcesPicker'


// URL-state key for the per-table storage-mode picker.
const STORAGE_MODE_PARAM = 'storage_modes'
type StorageMode = 'import' | 'direct_query' | 'dual'
const STORAGE_MODE_LABELS: Record<StorageMode, string> = {
  direct_query: 'DirectQuery',
  dual: 'Dual',
  import: 'Import',
}


function parseStorageModes(raw: string): Record<string, StorageMode> {
  // Wire format: "table1:dual,table2:directQuery,table3:import"
  const out: Record<string, StorageMode> = {}
  if (!raw) return out
  for (const pair of raw.split(',')) {
    const [t, m] = pair.split(':')
    if (t && (m === 'import' || m === 'direct_query' || m === 'dual')) {
      out[t] = m
    }
  }
  return out
}


function serializeStorageModes(map: Record<string, StorageMode>): string {
  return Object.entries(map)
    .map(([t, m]) => `${t}:${m}`)
    .join(',')
}


export function PreviewDiff(): JSX.Element {
  const [mvs] = useUrlList('mv')
  const [dashes] = useUrlList('dash')
  const [spaces] = useUrlList('space')
  const [exclude, setExclude] = useUrlList('exclude')
  const isExcluded = (name: string): boolean => exclude.includes(name)
  const toggleMeasure = (name: string): void =>
    setExclude(isExcluded(name) ? exclude.filter((n) => n !== name) : [...exclude, name])
  const [kind] = useUrlParam<DeliveryKind>('kind', 'xmla')
  const [targetId] = useUrlParam<string>('target_id', '')
  const [modelName] = useUrlParam<string>('model_name', '')
  const [xmlaMerge] = useUrlParam<string>('xmla_merge', 'false')
  const [storageModesRaw, setStorageModesRaw] = useUrlParam<string>(
    STORAGE_MODE_PARAM, '',
  )
  const storageModeOverrides = parseStorageModes(storageModesRaw)

  const preview = useSyncPreview()
  const [report, setReport] = useState<SyncReport | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const sources: SyncSourceRef[] = [
    ...mvs.map((id) => ({ kind: 'metric_view' as const, id })),
    ...dashes.map((id) => ({ kind: 'dashboard' as const, id })),
    ...spaces.map((id) => ({ kind: 'genie_space' as const, id })),
  ]
  const hasSources = sources.length > 0
  const hasTarget = !!targetId && !!modelName

  useEffect(() => {
    if (!hasSources || !hasTarget) return
    preview.mutate(
      {
        sources,
        target: { kind, target_id: targetId },
        model_name: modelName,
        xmla_merge: xmlaMerge === 'true',
        storage_modes: storageModeOverrides,
      },
      {
        onSuccess: (r) => setReport(r),
        onError: (e) =>
          setErr(e instanceof ApiClientError ? `${e.envelope.code}: ${e.message}` : String(e)),
      },
    )
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const backHref = `/target${window.location.search}`

  if (!hasSources) return <EmptyState message="No sources selected." backHref={backHref} />
  if (!hasTarget) return <EmptyState message="No target or model name set." backHref={backHref} />
  if (err) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 shadow-card">
        <div className="text-sm font-medium text-red-800">Failed to preview</div>
        <div className="mt-1 text-sm text-red-700">{err}</div>
        <a href={backHref} className="mt-3 inline-block text-sm text-red-800 underline">← Back</a>
      </div>
    )
  }
  if (!report) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-card">
        <div className="flex items-center justify-center gap-3 text-databricks-ink">
          <DatabricksMark className="h-8 w-8 animate-pulse" />
          <ArrowFlow className="h-3 w-10 animate-pulse text-databricks-red" />
          <PowerBiMark className="h-8 w-8 animate-pulse" />
        </div>
        <div className="mt-4 text-center text-sm font-medium text-databricks-ink">
          Translating SQL → DAX
        </div>
        <div className="mt-1 text-center text-xs text-slate-500">
          Reading {sources.length} source{sources.length === 1 ? '' : 's'}. First call against a
          cold SQL warehouse can take 30–60s.
        </div>
      </div>
    )
  }

  const applyHref = `/apply${window.location.search}`

  function toggle(key: string): void {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const measureRows = report.outcomes.filter((o) => o.object_kind === 'measure')
  const otherRows = report.outcomes.filter((o) => o.object_kind !== 'measure')
  const tableRows = (report.tables ?? []).filter((t) => !t.is_measures_table)

  function setTableMode(name: string, mode: StorageMode): void {
    const next: Record<string, StorageMode> = { ...storageModeOverrides }
    next[name] = mode
    setStorageModesRaw(serializeStorageModes(next))
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Step 3 of 3"
        title="Preview"
        subtitle={`Run ${report.run_id} — nothing has been written yet.`}
        action={
          <div className="flex items-center gap-2">
            <a
              href={backHref}
              className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
            >
              ← Back
            </a>
            <a
              href={applyHref}
              className="inline-flex items-center gap-2 rounded-md bg-databricks-mint px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-mint/90"
            >
              Apply →
            </a>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Created" v={report.summary.created} tone="ok" />
        <Stat label="Updated" v={report.summary.updated} tone="info" />
        <Stat label="Unchanged" v={report.summary.unchanged} tone="muted" />
        <Stat label="Needs review" v={report.summary.needs_manual_review} tone="warn" />
      </div>

      {tableRows.length > 0 && (
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="border-b border-slate-200 bg-slate-50/60 px-5 py-3">
            <div className="text-sm font-semibold text-databricks-ink">Tables</div>
            <div className="text-xs text-slate-500">
              Pick a storage mode per table. PBI Service won't let you change this
              after publish — Import caches all rows, DirectQuery queries live,
              Dual does both.
            </div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-white text-left text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-5 py-2">Table</th>
                <th className="px-3 py-2">UC path</th>
                <th className="px-3 py-2">Columns</th>
                <th className="px-3 py-2">Storage mode</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((t) => (
                <TableModeRow
                  key={t.name}
                  table={t}
                  override={storageModeOverrides[t.name]}
                  onChange={(m) => setTableMode(t.name, m)}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/60 px-5 py-3">
          <div>
            <div className="text-sm font-semibold text-databricks-ink">Measures</div>
            <div className="text-xs text-slate-500">
              {measureRows.length - exclude.length} of {measureRows.length} selected — uncheck to skip, click a row to see SQL → DAX
            </div>
          </div>
          <Legend />
        </div>
        <table className="w-full text-sm">
          <thead className="bg-white text-left text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="w-10 px-3 py-2">Sync</th>
              <th className="w-10 px-3 py-2"></th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Method</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {measureRows.map((o) => {
              const key = `${o.object_kind}:${o.name}`
              const isOpen = expanded.has(key)
              return (
                <MeasureRow
                  key={key}
                  outcome={o}
                  isOpen={isOpen}
                  onToggle={() => toggle(key)}
                  excluded={isExcluded(o.name)}
                  onToggleExclude={() => toggleMeasure(o.name)}
                />
              )
            })}
          </tbody>
        </table>
      </section>

      {otherRows.length > 0 && (
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="border-b border-slate-200 bg-slate-50/60 px-5 py-3 text-sm font-semibold text-databricks-ink">
            Other objects ({otherRows.length})
          </div>
          <ul className="divide-y divide-slate-100 text-sm">
            {otherRows.map((o) => (
              <li
                key={`${o.object_kind}:${o.name}`}
                className="flex items-center justify-between px-5 py-2"
              >
                <span className="font-mono">{o.name}</span>
                <span className="text-xs uppercase tracking-wider text-slate-500">
                  {o.object_kind} · {o.action}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}


function EmptyState(props: { message: string; backHref: string }): JSX.Element {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-card">
      <div className="text-sm text-amber-800">{props.message}</div>
      <a href={props.backHref} className="mt-3 inline-block text-sm text-amber-800 underline">
        ← Back
      </a>
    </div>
  )
}


function Legend(): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider">
      <LegendChip label="rule" cls="bg-emerald-100 text-emerald-800" />
      <LegendChip label="cache" cls="bg-blue-100 text-blue-800" />
      <LegendChip label="llm" cls="bg-violet-100 text-violet-800" />
      <LegendChip label="placeholder" cls="bg-amber-100 text-amber-800" />
    </div>
  )
}


function LegendChip(props: { label: string; cls: string }): JSX.Element {
  return (
    <span className={`rounded px-1.5 py-0.5 font-semibold ${props.cls}`}>{props.label}</span>
  )
}


function MeasureRow(props: {
  outcome: SyncOutcome
  isOpen: boolean
  onToggle: () => void
  excluded: boolean
  onToggleExclude: () => void
}): JSX.Element {
  const { outcome: o, isOpen, onToggle, excluded, onToggleExclude } = props
  const method = o.translation_method ?? 'n/a'
  const methodColor =
    method === 'rule'
      ? 'bg-emerald-100 text-emerald-800'
      : method === 'cache'
      ? 'bg-blue-100 text-blue-800'
      : method === 'llm'
      ? 'bg-violet-100 text-violet-800'
      : 'bg-amber-100 text-amber-800'

  return (
    <>
      <tr
        className={[
          'cursor-pointer border-t border-slate-100 transition-colors hover:bg-databricks-red/5',
          excluded ? 'opacity-50' : '',
        ].join(' ')}
        onClick={onToggle}
      >
        <td className="px-3 py-2">
          <input
            type="checkbox"
            checked={!excluded}
            onClick={(e) => e.stopPropagation()}
            onChange={onToggleExclude}
            className="h-4 w-4 accent-databricks-red align-middle"
            title={excluded ? 'Excluded from this sync' : 'Included in this sync'}
          />
        </td>
        <td className="px-3 py-2 text-slate-400">
          <span
            className={[
              'inline-block transition-transform',
              isOpen ? 'rotate-90 text-databricks-red' : '',
            ].join(' ')}
            aria-hidden="true"
          >
            ▸
          </span>
        </td>
        <td className="px-3 py-2 font-mono text-sm font-medium text-databricks-ink">
          {o.name}
        </td>
        <td className="px-3 py-2 text-xs uppercase tracking-wider text-slate-500">
          {o.action}
        </td>
        <td className="px-3 py-2">
          <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${methodColor}`}>
            {method}
          </span>
        </td>
        <td className="px-3 py-2 text-xs">
          {o.needs_manual_review ? (
            <span className="inline-flex items-center gap-1 text-amber-700">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              needs review
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              ok
            </span>
          )}
        </td>
      </tr>
      {isOpen && (
        <tr className="border-t border-slate-100 bg-slate-50/60">
          <td colSpan={5} className="px-5 py-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <DatabricksMark className="h-3.5 w-3.5" />
                  Before — Databricks SQL
                </div>
                <pre className="overflow-x-auto rounded-md border border-slate-200 bg-white p-3 font-mono text-xs text-slate-800">
                  {o.sql_expression ?? '(none)'}
                </pre>
              </div>
              <div>
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <PowerBiMark className="h-3.5 w-3.5" />
                  After — Power BI DAX
                </div>
                <pre className="overflow-x-auto rounded-md border border-slate-200 bg-white p-3 font-mono text-xs text-slate-800">
                  {o.dax ?? '(none)'}
                </pre>
              </div>
            </div>
            {o.warnings.length > 0 && (
              <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {o.warnings.map((w, i) => (
                  <div key={i}>• {w}</div>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}


function TableModeRow(props: {
  table: TableInfo
  override: StorageMode | undefined
  onChange: (mode: StorageMode) => void
}): JSX.Element {
  const { table, override, onChange } = props
  const effective: StorageMode = override ?? (table.storage_mode as StorageMode)
  const isOverridden = override !== undefined && override !== table.storage_mode
  return (
    <tr className="border-t border-slate-100">
      <td className="px-5 py-2 font-mono text-sm font-medium text-databricks-ink">
        {table.name}
      </td>
      <td className="px-3 py-2 text-xs text-slate-600">{table.uc_path ?? '—'}</td>
      <td className="px-3 py-2 text-xs text-slate-500">{table.column_count}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <select
            value={effective}
            onChange={(e) => onChange(e.target.value as StorageMode)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20"
          >
            <option value="direct_query">{STORAGE_MODE_LABELS.direct_query}</option>
            <option value="dual">{STORAGE_MODE_LABELS.dual}</option>
            <option value="import">{STORAGE_MODE_LABELS.import}</option>
          </select>
          {isOverridden && (
            <span className="text-[10px] uppercase tracking-wider text-amber-700">
              overridden
            </span>
          )}
        </div>
      </td>
    </tr>
  )
}


function Stat(props: {
  label: string
  v: number
  tone: 'ok' | 'info' | 'warn' | 'muted'
}): JSX.Element {
  const toneCls =
    props.tone === 'ok'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : props.tone === 'info'
      ? 'border-blue-200 bg-blue-50 text-blue-900'
      : props.tone === 'warn' && props.v > 0
      ? 'border-amber-300 bg-amber-50 text-amber-900'
      : 'border-slate-200 bg-white text-slate-700'
  return (
    <div className={`rounded-xl border p-4 shadow-card ${toneCls}`}>
      <div className="text-xs font-medium uppercase tracking-wider opacity-70">
        {props.label}
      </div>
      <div className="mt-1 text-3xl font-semibold leading-none">{props.v}</div>
    </div>
  )
}
