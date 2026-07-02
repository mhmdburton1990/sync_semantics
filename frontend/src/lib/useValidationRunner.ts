import { useEffect, useState } from 'react'
import { api, ApiClientError } from '../api'
import type {
  DateColumnRef,
  MeasureValidation,
  SyncSourceRef,
  ValidationJobStatus,
  ValidationSummary,
} from '../types'

export type Timeframe = 'all' | 'day' | 'week' | 'month' | 'quarter' | 'year'

function summarize(results: MeasureValidation[]): ValidationSummary {
  return {
    passed: results.filter((r) => r.status === 'passed').length,
    failed: results.filter((r) => r.status === 'failed').length,
    skipped: results.filter((r) => r.status === 'skipped').length,
  }
}

export interface ValidationRunnerSeed {
  sources: SyncSourceRef[]
  modelName: string
  datasetId: string
  workspaceId: string
  runId: string | null
  initialResults?: MeasureValidation[]
  initialSummary?: ValidationSummary
  initialJobId?: string | null
  onJobIdChange?: (id: string | null) => void
  initialDimSqlRef?: string
  onDimSqlRefChange?: (v: string) => void
  initialTimeframe?: Timeframe
  onTimeframeChange?: (v: Timeframe) => void
  initialDateTable?: string
  onDateTableChange?: (v: string) => void
  initialDateColumn?: string
  onDateColumnChange?: (v: string) => void
  excludeMeasures?: string[]
}

export interface ValidationRunnerState {
  dims: string[]
  hasDateCol: boolean
  dimsLoaded: boolean
  dimsError: string | null
  dimSqlRef: string
  setDimSqlRef: (v: string) => void
  timeframe: Timeframe
  setTimeframe: (v: Timeframe) => void
  dateColumns: DateColumnRef[]
  dateTable: string
  setDateTable: (v: string) => void
  dateColumn: string
  setDateColumn: (v: string) => void
  job: ValidationJobStatus | null
  jobId: string | null
  starting: boolean
  canceling: boolean
  validateErr: string | null
  startValidation: () => Promise<void>
  cancelValidation: () => Promise<void>
}

export function useValidationRunner(seed: ValidationRunnerSeed): ValidationRunnerState {
  const { sources, modelName, datasetId, workspaceId, runId } = seed
  const [jobId, setJobId] = useState<string | null>(seed.initialJobId ?? null)
  const [job, setJob] = useState<ValidationJobStatus | null>(
    seed.initialResults
      ? {
          status: 'done',
          total: seed.initialResults.length,
          results: seed.initialResults,
          summary: seed.initialSummary ?? summarize(seed.initialResults),
          error: null,
          current: null,
        }
      : null,
  )
  const [starting, setStarting] = useState(false)
  const [validateErr, setValidateErr] = useState<string | null>(null)
  const [dims, setDims] = useState<string[]>([])
  const [hasDateCol, setHasDateCol] = useState(false)
  const [dimsLoaded, setDimsLoaded] = useState(false)
  const [dimsError, setDimsError] = useState<string | null>(null)
  const [dimSqlRef, setDimSqlRefState] = useState(seed.initialDimSqlRef ?? '')
  const [timeframe, setTimeframeState] = useState<Timeframe>(seed.initialTimeframe ?? 'all')
  const [dateTable, setDateTableState] = useState(seed.initialDateTable ?? '')
  const [dateColumn, setDateColumnState] = useState(seed.initialDateColumn ?? '')
  const [dateColumns, setDateColumns] = useState<DateColumnRef[]>([])
  const [canceling, setCanceling] = useState(false)

  function setDimSqlRef(v: string): void {
    setDimSqlRefState(v)
    seed.onDimSqlRefChange?.(v)
  }
  function setTimeframe(v: Timeframe): void {
    setTimeframeState(v)
    seed.onTimeframeChange?.(v)
  }
  function setDateColumn(v: string): void {
    setDateColumnState(v)
    seed.onDateColumnChange?.(v)
  }
  function setDateTable(v: string): void {
    setDateTableState(v)
    seed.onDateTableChange?.(v)
    // Reset the column to the first candidate of the newly chosen table.
    const first = dateColumns.find((d) => d.table === v)?.column ?? ''
    setDateColumnState(first)
    seed.onDateColumnChange?.(first)
  }

  const sourcesKey = sources.map((s) => `${s.kind}:${s.id}`).join(',')

  // Load the candidate dimensions for this model once.
  useEffect(() => {
    void (async () => {
      try {
        const d = await api.listValidateDimensions({ sources, model_name: modelName })
        setDims(d.dimensions)
        setHasDateCol(d.has_date_column)
        setDateColumns(d.date_columns)
        const first = d.date_columns[0]
        if (!seed.initialDateTable && first) {
          setDateTableState(first.table)
          setDateColumnState(first.column)
        }
      } catch (e) {
        // Grand total still works without the dimension list; surface why it's empty.
        setDimsError(e instanceof ApiClientError ? e.envelope.message : String(e))
      } finally {
        setDimsLoaded(true)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourcesKey, modelName])

  async function startValidation(): Promise<void> {
    setValidateErr(null)
    setStarting(true)
    setCanceling(false)
    setJob(null)
    try {
      const res = await api.startValidate({
        sources,
        model_name: modelName,
        dataset_id: datasetId,
        workspace_id: workspaceId,
        dim_sql_ref: dimSqlRef || null,
        timeframe,
        date_table: dateTable || null,
        date_column: dateColumn || null,
        exclude_measures: seed.excludeMeasures ?? [],
        run_id: runId,
      })
      setJobId(res.job_id)
      seed.onJobIdChange?.(res.job_id)
      setJob({
        status: 'running',
        total: res.total,
        results: [],
        summary: { passed: 0, failed: 0, skipped: 0 },
        error: null,
        current: null,
      })
    } catch (e) {
      setValidateErr(e instanceof ApiClientError ? e.envelope.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  async function cancelValidation(): Promise<void> {
    if (!jobId) return
    // Stays true until the job actually reaches a terminal state — the backend
    // cancels between measures, so polling flips the status a moment later.
    setCanceling(true)
    try {
      await api.cancelValidateJob(jobId)
    } catch (e) {
      setValidateErr(e instanceof ApiClientError ? e.envelope.message : String(e))
      setCanceling(false)
    }
  }

  // Clear the canceling flag once the job has stopped, re-enabling Re-validate.
  useEffect(() => {
    if (job && (job.status === 'done' || job.status === 'error' || job.status === 'canceled')) {
      setCanceling(false)
    }
  }, [job?.status])

  useEffect(() => {
    if (!jobId) return
    if (job && (job.status === 'done' || job.status === 'error' || job.status === 'canceled')) {
      return
    }
    const timer = setInterval(() => {
      void (async () => {
        try {
          setJob(await api.getValidateJob(jobId))
        } catch (e) {
          setValidateErr(e instanceof ApiClientError ? e.envelope.message : String(e))
          clearInterval(timer)
        }
      })()
    }, 1500)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, job?.status])

  return {
    dims, hasDateCol, dimsLoaded, dimsError, dimSqlRef, setDimSqlRef,
    timeframe, setTimeframe, dateColumns, dateTable, setDateTable, dateColumn, setDateColumn,
    job, jobId, starting, canceling, validateErr,
    startValidation, cancelValidation,
  }
}
