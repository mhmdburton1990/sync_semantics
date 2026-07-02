import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useValidationRunner } from './useValidationRunner'
import { api } from '../api'

// Mock the API so the hook's dimension-fetch and polling effects don't hit the network.
vi.mock('../api', () => ({
  api: {
    listValidateDimensions: vi.fn().mockResolvedValue({
      dimensions: [], has_date_column: false, date_columns: [],
    }),
    startValidate: vi.fn().mockResolvedValue({ job_id: 'j1', total: 1 }),
    getValidateJob: vi.fn().mockResolvedValue({
      status: 'running', total: 0, results: [], summary: { passed: 0, failed: 0, skipped: 0 }, error: null,
    }),
    cancelValidateJob: vi.fn(),
  },
  ApiClientError: class ApiClientError extends Error {},
}))

const seed = {
  sources: [],
  modelName: 'm',
  datasetId: 'd',
  workspaceId: 'w',
  runId: 'r',
}

describe('useValidationRunner', () => {
  it('seeds jobId from initialJobId (resume)', () => {
    const { result } = renderHook(() => useValidationRunner({ ...seed, initialJobId: 'job-7' }))
    expect(result.current.jobId).toBe('job-7')
  })

  it('jobId is null without initialJobId', () => {
    const { result } = renderHook(() => useValidationRunner(seed))
    expect(result.current.jobId).toBeNull()
  })

  it('seeds date table/column from initial values and forwards them on start', async () => {
    vi.mocked(api.listValidateDimensions).mockResolvedValue({
      dimensions: [], has_date_column: true,
      date_columns: [{ table: 'orders', column: 'o_orderdate' }],
    })
    const { result } = renderHook(() =>
      useValidationRunner({
        ...seed, runId: null,
        sources: [{ kind: 'metric_view', id: 'main.s.mv' }],
        initialDateTable: 'orders', initialDateColumn: 'o_orderdate',
        initialTimeframe: 'quarter',
      }),
    )
    expect(result.current.dateTable).toBe('orders')
    expect(result.current.dateColumn).toBe('o_orderdate')
    expect(result.current.timeframe).toBe('quarter')
    await act(async () => { await result.current.startValidation() })
    expect(api.startValidate).toHaveBeenCalledWith(
      expect.objectContaining({ date_table: 'orders', date_column: 'o_orderdate', timeframe: 'quarter' }),
    )
  })

  it('keeps canceling true after a cancel request until the job stops', async () => {
    vi.mocked(api.cancelValidateJob).mockResolvedValue(undefined as never)
    const { result } = renderHook(() => useValidationRunner({ ...seed, initialJobId: 'job-7' }))
    await act(async () => { await result.current.cancelValidation() })
    expect(api.cancelValidateJob).toHaveBeenCalledWith('job-7')
    expect(result.current.canceling).toBe(true)
  })

  it('invokes onDateTableChange / onTimeframeChange from setters', () => {
    vi.mocked(api.listValidateDimensions).mockResolvedValue({
      dimensions: [], has_date_column: true, date_columns: [],
    })
    const onDateTableChange = vi.fn()
    const onTimeframeChange = vi.fn()
    const { result } = renderHook(() =>
      useValidationRunner({ ...seed, onDateTableChange, onTimeframeChange }),
    )
    act(() => { result.current.setDateTable('orders') })
    act(() => { result.current.setTimeframe('week') })
    expect(onDateTableChange).toHaveBeenCalledWith('orders')
    expect(onTimeframeChange).toHaveBeenCalledWith('week')
  })
})
