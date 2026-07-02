import { useMutation, useQuery } from '@tanstack/react-query'
import { api, ApiClientError } from '../api'
import { useSelectedCatalog, useSelectedSchema } from '../catalog'
import { useWarehouseId } from '../warehouse'
import type { SyncRequest } from '../types'

export function useWarehouses() {
  return useQuery({ queryKey: ['warehouses'], queryFn: api.listWarehouses })
}
// Source/sync queries are scoped by the selected warehouse id so switching
// warehouses refetches automatically.
export function useMetricViews(catalog?: string, schema?: string) {
  const wh = useWarehouseId()
  return useQuery({
    queryKey: ['sources', 'metric_views', wh, catalog ?? '', schema ?? ''],
    queryFn: () => api.listMetricViews(catalog, schema),
    // Only fire when a warehouse + both catalog and schema are picked.
    // Lists could be huge across all catalogs; force the user to scope first.
    enabled: !!wh && !!catalog && !!schema,
  })
}
export function useCatalogs() {
  const wh = useWarehouseId()
  return useQuery({
    queryKey: ['sources', 'catalogs', wh],
    queryFn: api.listCatalogs,
    enabled: !!wh,
  })
}
export function useSchemas(catalog: string | null) {
  const wh = useWarehouseId()
  return useQuery({
    queryKey: ['sources', 'schemas', wh, catalog ?? ''],
    queryFn: () => api.listSchemas(catalog!),
    enabled: !!wh && !!catalog,
  })
}
export function useDashboards() {
  const wh = useWarehouseId()
  return useQuery({
    queryKey: ['sources', 'dashboards', wh],
    queryFn: api.listDashboards,
  })
}
export function useGenieSpaces() {
  const wh = useWarehouseId()
  return useQuery({
    queryKey: ['sources', 'genie_spaces', wh],
    queryFn: api.listGenieSpaces,
  })
}
export function useFabricWorkspaces() {
  return useQuery({
    queryKey: ['fabric', 'workspaces'],
    queryFn: api.listFabricWorkspaces,
    // Listing 401s/403s if the Fabric SP isn't configured/permissioned;
    // surface that to the UI via .error rather than retrying.
    retry: false,
  })
}
export function useHistory() {
  // History reads a UC Delta table in the selected catalog+schema, via the
  // selected warehouse — guard on all three so the History tab doesn't 400
  // before they're picked, and re-key so switching any refetches.
  const wh = useWarehouseId()
  const catalog = useSelectedCatalog()
  const schema = useSelectedSchema()
  return useQuery({
    queryKey: ['history', wh, catalog, schema],
    queryFn: api.listHistory,
    enabled: !!wh && !!catalog && !!schema,
  })
}
export function useRunDetail(runId: string) {
  const wh = useWarehouseId()
  const catalog = useSelectedCatalog()
  const schema = useSelectedSchema()
  return useQuery({
    queryKey: ['history', wh, catalog, schema, runId],
    queryFn: () => api.getRun(runId),
    enabled: !!wh && !!catalog && !!schema && !!runId,
  })
}
export function useCacheStatus() {
  return useQuery({ queryKey: ['cache'], queryFn: api.cacheStatus })
}
export function useSyncPreview() {
  return useMutation({ mutationFn: (req: SyncRequest) => api.syncPreview(req) })
}
export { ApiClientError }
