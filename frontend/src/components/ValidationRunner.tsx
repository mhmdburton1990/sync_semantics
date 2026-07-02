import { useValidationRunner, type ValidationRunnerSeed } from '../lib/useValidationRunner'
import { ValidationPanel } from './ValidationPanel'

export function ValidationRunner(props: ValidationRunnerSeed): JSX.Element {
  const v = useValidationRunner(props)
  // Before the dimensions/date-columns fetch returns we still want resumed
  // selections to display, so fall back to the seeded value as the sole option.
  const tableOptions = v.dateColumns.length
    ? [...new Set(v.dateColumns.map((d) => d.table))]
    : (v.dateTable ? [v.dateTable] : [])
  const columnOptions = v.dateColumns.length
    ? v.dateColumns.filter((d) => d.table === v.dateTable).map((d) => d.column)
    : (v.dateColumn ? [v.dateColumn] : [])
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-card space-y-3">
        <div className="text-sm font-semibold text-databricks-ink">Validate published model</div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-600">
            Dimension
            <select
              value={v.dimsLoaded ? v.dimSqlRef : '__loading'}
              onChange={(e) => v.setDimSqlRef(e.target.value)}
              disabled={!v.dimsLoaded}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
            >
              {v.dimsLoaded ? (
                <>
                  <option value="">Grand total only</option>
                  {v.dims.map((d) => <option key={d} value={d}>{d}</option>)}
                </>
              ) : (
                <option value="__loading">Loading dimensions…</option>
              )}
            </select>
          </label>
          {tableOptions.length > 0 && (
            <>
              <label className="text-xs text-slate-600">
                Calendar table
                <select
                  value={v.dateTable}
                  onChange={(e) => v.setDateTable(e.target.value)}
                  disabled={!v.dimsLoaded}
                  className="mt-1 block rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
                >
                  {tableOptions.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-slate-600">
                Date column
                <select
                  value={v.dateColumn}
                  onChange={(e) => v.setDateColumn(e.target.value)}
                  disabled={!v.dimsLoaded}
                  className="mt-1 block rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
                >
                  {columnOptions.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
            </>
          )}
          <label className="text-xs text-slate-600">
            Timeframe
            <select
              value={v.timeframe}
              onChange={(e) => v.setTimeframe(e.target.value as typeof v.timeframe)}
              disabled={!v.hasDateCol}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
            >
              <option value="all">All data</option>
              <option value="day">Last day</option>
              <option value="week">Last week</option>
              <option value="month">Last month</option>
              <option value="quarter">Last quarter</option>
              <option value="year">Last year</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void v.startValidation()}
            disabled={v.starting || (!!v.job && (v.job.status === 'running' || v.job.status === 'pending'))}
            className="inline-flex items-center rounded-md bg-databricks-ink px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-databricks-ink/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {v.starting ? 'Starting…' : (v.jobId || v.job) ? 'Re-validate' : 'Validate now'}
          </button>
          {!!v.job && (v.job.status === 'running' || v.job.status === 'pending') && (
            <button
              type="button"
              onClick={() => void v.cancelValidation()}
              disabled={v.canceling}
              className="inline-flex items-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {v.canceling ? 'Canceling…' : 'Cancel'}
            </button>
          )}
        </div>
        {v.dimsError && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Couldn&apos;t load dimensions ({v.dimsError}). Grand-total validation still works.
          </div>
        )}
        {v.dimsLoaded && !v.dimsError && !v.hasDateCol && (
          <div className="text-xs text-slate-400">
            No date column in this model — timeframe filtering unavailable.
          </div>
        )}
        {v.canceling && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Canceling validation — stopping queries on Databricks and Power BI. You can re-validate
            once it stops (any in-flight query finishes first).
          </div>
        )}
        {v.validateErr && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {v.validateErr}
          </div>
        )}
      </div>
      {v.job && (
        <ValidationPanel
          results={v.job.results}
          summary={v.job.summary}
          running={v.job.status === 'running' || v.job.status === 'pending'}
          total={v.job.total}
          current={v.job.current}
        />
      )}
    </div>
  )
}
