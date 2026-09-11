import { useEffect, useState } from 'react'
import {
  useCatalogs,
  useMetricViews,
  useSchemas,
} from '../lib/queryClient'
import { setSelectedCatalog, setSelectedSchema } from '../catalog'
import { useUrlList, useUrlParam } from '../lib/url-state'
import type { SourceKind } from '../types'
import { DatabricksMark } from '../components/BrandMarks'


// Only metric views are offered for now; dashboards and Genie spaces are
// intentionally not listed (the reader/back end still supports them).
const TABS: Array<{ key: SourceKind; label: string; description: string }> = [
  {
    key: 'metric_view',
    label: 'Metric Views',
    description: 'Unity Catalog metric views (curated measures + dimensions)',
  },
]


export function SourcesPicker(): JSX.Element {
  const [active, setActive] = useState<SourceKind>('metric_view')
  const [selectedMVs, setSelectedMVs] = useUrlList('mv')
  const [catalog, setCatalog] = useUrlParam<string>('catalog', '')
  const [schema, setSchema] = useUrlParam<string>('schema', '')

  // Persist the chosen catalog+schema so the History tab (a separate route) can
  // scope run history to that namespace. Covers manual selection and deep links.
  useEffect(() => {
    if (catalog) setSelectedCatalog(catalog)
  }, [catalog])
  useEffect(() => {
    if (schema) setSelectedSchema(schema)
  }, [schema])

  const catalogs = useCatalogs()
  const schemas = useSchemas(catalog || null)
  const mvs = useMetricViews(catalog || undefined, schema || undefined)

  const totalSelected = selectedMVs.length

  function toggle(list: string[], setter: (v: string[]) => void, id: string): void {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  }

  const activeTab = TABS.find((t) => t.key === active)!

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Step 1 of 3"
        title="Pick sources"
        subtitle="Select Databricks objects to sync into a Power BI semantic model."
        action={
          <a
            href={`/target${window.location.search}`}
            className={[
              'inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition',
              totalSelected > 0
                ? 'bg-databricks-red text-white shadow-sm hover:bg-databricks-red/90'
                : 'pointer-events-none bg-slate-200 text-slate-500',
            ].join(' ')}
          >
            Next: target
            <span
              className={[
                'rounded-full px-2 py-0.5 text-xs',
                totalSelected > 0 ? 'bg-white/20' : 'bg-slate-300/60',
              ].join(' ')}
            >
              {totalSelected}
            </span>
          </a>
        }
      />

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
        <div className="flex gap-1 border-b border-slate-200 bg-slate-50/60 px-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setActive(t.key)}
              className={[
                '-mb-px border-b-2 px-4 py-3 text-sm font-medium transition',
                active === t.key
                  ? 'border-databricks-red text-databricks-ink'
                  : 'border-transparent text-slate-500 hover:text-slate-800',
              ].join(' ')}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="px-5 py-2 text-xs text-slate-500">{activeTab.description}</div>

        {active === 'metric_view' && (
          <>
            <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 bg-white px-5 py-3">
              <label className="flex-1 min-w-[180px]">
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">
                  Catalog
                </div>
                <select
                  value={catalog}
                  onChange={(e) => {
                    setCatalog(e.target.value)
                    setSchema('')
                  }}
                  disabled={catalogs.isLoading || !!catalogs.error}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20"
                >
                  <option value="">
                    {catalogs.isLoading ? 'Loading…' : '— pick a catalog —'}
                  </option>
                  {(catalogs.data ?? []).map((c) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </label>
              <label className="flex-1 min-w-[180px]">
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">
                  Schema
                </div>
                <select
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  disabled={!catalog || schemas.isLoading || !!schemas.error}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20 disabled:bg-slate-50 disabled:text-slate-400"
                >
                  <option value="">
                    {!catalog
                      ? '— pick a catalog first —'
                      : schemas.isLoading
                      ? 'Loading…'
                      : '— pick a schema —'}
                  </option>
                  {(schemas.data ?? []).map((s) => (
                    <option key={s.name} value={s.name}>{s.name}</option>
                  ))}
                </select>
              </label>
            </div>
            {!catalog || !schema ? (
              <div className="px-5 py-8 text-center text-sm text-slate-500">
                Pick a catalog and schema above to list metric views.
              </div>
            ) : (
              <SourceList
                items={(mvs.data ?? []).map((m) => ({
                  id: m.fully_qualified_name,
                  label: m.fully_qualified_name,
                  hint: m.description,
                }))}
                selected={selectedMVs}
                onToggle={(id) => toggle(selectedMVs, setSelectedMVs, id)}
                loading={mvs.isLoading}
                error={mvs.error}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}


export function PageHeader(props: {
  eyebrow: string
  title: string
  subtitle?: string
  action?: React.ReactNode
}): JSX.Element {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-databricks-red">
          {props.eyebrow}
        </div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-databricks-ink">
          {props.title}
        </h1>
        {props.subtitle && (
          <p className="mt-1 text-sm text-slate-600">{props.subtitle}</p>
        )}
      </div>
      {props.action && <div className="flex items-center">{props.action}</div>}
    </div>
  )
}


interface Item { id: string; label: string; hint?: string | null }


function SourceList(props: {
  items: Item[]
  selected: string[]
  onToggle: (id: string) => void
  loading: boolean
  error: unknown
}): JSX.Element {
  if (props.loading) {
    return (
      <div className="flex items-center gap-3 px-5 py-12 text-sm text-slate-500">
        <span className="h-2 w-2 animate-pulse rounded-full bg-databricks-red" />
        Loading from Databricks…
      </div>
    )
  }
  if (props.error) {
    return (
      <div className="px-5 py-8 text-sm text-red-600">
        Failed to load: {String(props.error)}
      </div>
    )
  }
  if (props.items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-5 py-12 text-center">
        <DatabricksMark className="h-8 w-8 opacity-50" />
        <div className="text-sm text-slate-500">Nothing here yet.</div>
        <div className="text-xs text-slate-400">
          Pick a SQL warehouse above, then this list will populate from your workspace.
        </div>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-slate-100">
      {props.items.map((it) => {
        const checked = props.selected.includes(it.id)
        return (
          <li
            key={it.id}
            className={[
              'flex cursor-pointer items-center gap-3 px-5 py-3 transition-colors',
              checked ? 'bg-databricks-red/5' : 'hover:bg-slate-50',
            ].join(' ')}
            onClick={() => props.onToggle(it.id)}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => props.onToggle(it.id)}
              onClick={(e) => e.stopPropagation()}
              className="h-4 w-4 cursor-pointer accent-databricks-red"
            />
            <div className="min-w-0 flex-1">
              <div className="truncate font-mono text-sm text-databricks-ink">{it.label}</div>
              {it.hint && (
                <div className="truncate text-xs text-slate-500">{it.hint}</div>
              )}
            </div>
            {checked && (
              <span className="rounded-full bg-databricks-red px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white">
                selected
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}
