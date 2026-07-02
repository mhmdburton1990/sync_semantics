import { authHeaders } from './auth'
import { historyHeaders } from './catalog'
import { warehouseHeaders } from './warehouse'
import type {
  ApiError,
  CacheStatus,
  CatalogSummary,
  DashboardSummary,
  FabricWorkspaceSummary,
  GenieSpaceSummary,
  HistoryEntry,
  MetricViewSummary,
  RunDetail,
  SchemaSummary,
  StartValidationResponse,
  SyncReport,
  SyncRequest,
  ValidateRequest,
  ValidationDimensionsResponse,
  ValidationJobStatus,
  WarehouseSummary,
} from './types'

export class ApiClientError extends Error {
  constructor(public readonly envelope: ApiError, public readonly status: number) {
    super(envelope.message)
    this.name = 'ApiClientError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...warehouseHeaders(),
      ...historyHeaders(),
      ...(init?.headers ?? {}),
    },
  })
  if (!resp.ok) {
    const body = (await resp.json().catch(() => null)) as ApiError | null
    throw new ApiClientError(
      body ?? { code: 'http_error', message: resp.statusText },
      resp.status,
    )
  }
  return (await resp.json()) as T
}

export const api = {
  listWarehouses: () => request<WarehouseSummary[]>('/api/warehouses'),
  listMetricViews: (catalog?: string, schema?: string) => {
    const p = new URLSearchParams()
    if (catalog) p.set('catalog', catalog)
    if (schema) p.set('schema', schema)
    const qs = p.toString()
    return request<MetricViewSummary[]>(
      qs ? `/api/sources/metric_views?${qs}` : '/api/sources/metric_views',
    )
  },
  listCatalogs: () => request<CatalogSummary[]>('/api/sources/catalogs'),
  listSchemas: (catalog: string) =>
    request<SchemaSummary[]>(
      `/api/sources/catalogs/${encodeURIComponent(catalog)}/schemas`,
    ),
  listDashboards: () => request<DashboardSummary[]>('/api/sources/dashboards'),
  listGenieSpaces: () => request<GenieSpaceSummary[]>('/api/sources/genie_spaces'),
  listFabricWorkspaces: () =>
    request<FabricWorkspaceSummary[]>('/api/fabric/workspaces'),
  syncPreview: (req: SyncRequest) =>
    request<SyncReport>('/api/sync/preview', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  listHistory: () => request<HistoryEntry[]>('/api/sync/history'),
  getRun: (runId: string) =>
    request<RunDetail>(`/api/sync/history/${encodeURIComponent(runId)}`),
  // The confidence report endpoint requires the OBO + X-Warehouse-Id headers,
  // which only fetch() injects — a raw <a> navigation would 400. Fetch the HTML
  // here so the caller can open it as a blob.
  getReportHtml: async (runId: string): Promise<string> => {
    const resp = await fetch(
      `/api/sync/history/${encodeURIComponent(runId)}/report.html`,
      { headers: { ...authHeaders(), ...warehouseHeaders(), ...historyHeaders() } },
    )
    if (!resp.ok) {
      const body = (await resp.json().catch(() => null)) as ApiError | null
      throw new ApiClientError(
        body ?? { code: 'http_error', message: resp.statusText },
        resp.status,
      )
    }
    return resp.text()
  },
  cacheStatus: () => request<CacheStatus>('/api/cache/status'),
  clearCache: () => request<CacheStatus>('/api/cache', { method: 'DELETE' }),
  startValidate: (req: ValidateRequest) =>
    request<StartValidationResponse>('/api/sync/validate/start', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  getValidateJob: (jobId: string) =>
    request<ValidationJobStatus>(`/api/sync/validate/jobs/${encodeURIComponent(jobId)}`),
  listValidateDimensions: (req: { sources: { kind: string; id: string }[]; model_name: string }) =>
    request<ValidationDimensionsResponse>('/api/sync/validate/dimensions', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  cancelValidateJob: (jobId: string) =>
    request<ValidationJobStatus>(`/api/sync/validate/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    }),
}
