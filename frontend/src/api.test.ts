import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api, ApiClientError } from './api'
import { setDevToken } from './auth'

describe('api client', () => {
  beforeEach(() => {
    setDevToken('dev-tok')
  })

  it('attaches OBO header on every request', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await api.listMetricViews()
    const [, init] = spy.mock.calls[0]!
    expect((init?.headers as Record<string, string>)['X-Forwarded-Access-Token']).toBe(
      'dev-tok',
    )
  })

  it('throws ApiClientError with envelope on non-200', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({ code: 'missing_obo_token', message: 'header missing' }),
        { status: 401 },
      ),
    )
    await expect(api.listMetricViews()).rejects.toThrow(ApiClientError)
  })

  it('startValidate posts to /start and getValidateJob polls the job', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'j1', total: 3 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'done', total: 3, results: [], summary: { passed: 0, failed: 0, skipped: 3 }, error: null,
      }), { status: 200 }))
    const start = await api.startValidate({
      sources: [{ kind: 'metric_view', id: 'm' }], model_name: 's',
      dataset_id: 'd', workspace_id: 'w', dim_sql_ref: null,
    })
    expect(start.job_id).toBe('j1')
    expect(spy.mock.calls[0]![0]).toBe('/api/sync/validate/start')
    const job = await api.getValidateJob('j1')
    expect(job.status).toBe('done')
    expect(spy.mock.calls[1]![0]).toBe('/api/sync/validate/jobs/j1')
  })

  it('listValidateDimensions POSTs to /api/sync/validate/dimensions', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ dimensions: ['region', 'product'], has_date_column: true }), { status: 200 }),
    )
    const result = await api.listValidateDimensions({
      sources: [{ kind: 'metric_view', id: 'm' }],
      model_name: 's',
    })
    expect(spy.mock.calls[0]![0]).toBe('/api/sync/validate/dimensions')
    expect((spy.mock.calls[0]![1] as RequestInit).method).toBe('POST')
    expect(result.dimensions).toEqual(['region', 'product'])
    expect(result.has_date_column).toBe(true)
  })

  it('cancelValidateJob POSTs to /api/sync/validate/jobs/j1/cancel', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({
        status: 'canceled', total: 3, results: [], summary: { passed: 0, failed: 0, skipped: 0 }, error: null,
      }), { status: 200 }),
    )
    const job = await api.cancelValidateJob('j1')
    expect(spy.mock.calls[0]![0]).toBe('/api/sync/validate/jobs/j1/cancel')
    expect((spy.mock.calls[0]![1] as RequestInit).method).toBe('POST')
    expect(job.status).toBe('canceled')
  })
})
