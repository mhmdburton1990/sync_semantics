import { useMemo } from 'react'
import { useUrlList, useUrlParam } from '../lib/url-state'
import { useWarehouseId } from '../warehouse'
import type { SyncSourceRef } from '../types'
import { ValidationRunner } from '../components/ValidationRunner'
import { PageHeader } from './SourcesPicker'


export function Validate(): JSX.Element {
  const wh = useWarehouseId()
  const [mvs] = useUrlList('mv')
  const [dashes] = useUrlList('dash')
  const [spaces] = useUrlList('space')
  const [exclude] = useUrlList('exclude')
  const [modelName] = useUrlParam<string>('model_name', '')
  const [targetId] = useUrlParam<string>('target_id', '')
  const [datasetId] = useUrlParam<string>('dataset_id', '')
  const [runId] = useUrlParam<string>('run_id', '')
  const [vjob, setVjob] = useUrlParam<string>('vjob', '')
  const [dim, setDim] = useUrlParam<string>('dim', '')
  const [tf, setTf] = useUrlParam<'all' | 'day' | 'week' | 'month' | 'quarter' | 'year'>('tf', 'all')
  const [dateTable, setDateTable] = useUrlParam<string>('date_table', '')
  const [dateCol, setDateCol] = useUrlParam<string>('date_col', '')

  const sources = useMemo<SyncSourceRef[]>(
    () => [
      ...mvs.map((id) => ({ kind: 'metric_view' as const, id })),
      ...dashes.map((id) => ({ kind: 'dashboard' as const, id })),
      ...spaces.map((id) => ({ kind: 'genie_space' as const, id })),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mvs.join(','), dashes.join(','), spaces.join(',')],
  )

  if (!wh) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Validate" title="Validate model" />
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          Pick a SQL warehouse above to validate.
        </div>
      </div>
    )
  }
  if (!datasetId) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Validate" title="Validate model" />
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-card">
          Publish a model to Power BI first (from Preview → Apply), then validate it here.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Validate"
        title={modelName || 'Model'}
        subtitle="Compare the published model's DAX measures against the Databricks source."
      />
      <ValidationRunner
        sources={sources}
        modelName={modelName}
        datasetId={datasetId}
        workspaceId={targetId}
        runId={runId || null}
        initialJobId={vjob || null}
        onJobIdChange={(id) => setVjob(id ?? '')}
        initialDimSqlRef={dim}
        onDimSqlRefChange={setDim}
        initialTimeframe={tf}
        onTimeframeChange={setTf}
        initialDateTable={dateTable}
        onDateTableChange={setDateTable}
        initialDateColumn={dateCol}
        onDateColumnChange={setDateCol}
        excludeMeasures={exclude}
      />
    </div>
  )
}
