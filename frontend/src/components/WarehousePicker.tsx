// Persistent warehouse picker rendered in the top nav. Selection is stored in
// localStorage and sent as X-Warehouse-Id on every API call (see warehouse.ts).

import { useWarehouses } from '../lib/queryClient'
import { setWarehouseId, useWarehouseId } from '../warehouse'

export function WarehousePicker(): JSX.Element {
  const selected = useWarehouseId() ?? ''
  const warehouses = useWarehouses()

  if (warehouses.isLoading) {
    return <span className="text-xs text-slate-400">Loading warehouses…</span>
  }
  if (warehouses.error) {
    return (
      <span className="text-xs text-red-300">
        Warehouses error: {String(warehouses.error)}
      </span>
    )
  }
  const items = warehouses.data ?? []
  if (items.length === 0) {
    return <span className="text-xs text-slate-400">No accessible warehouses</span>
  }

  return (
    <label className="flex items-center gap-2 text-xs text-slate-300">
      <svg
        viewBox="0 0 20 20"
        className="h-4 w-4 text-databricks-mint"
        aria-hidden="true"
      >
        <path
          fill="currentColor"
          d="M3 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3H3V5Zm0 5h14v3H3v-3Zm0 5h14v0a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Zm3-8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Zm0 5a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"
        />
      </svg>
      <span className="font-medium text-slate-200">Warehouse</span>
      <select
        value={selected}
        onChange={(e) => setWarehouseId(e.target.value || null)}
        className="rounded-md border border-white/10 bg-databricks-ink/40 px-2 py-1 text-xs text-white focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/40"
      >
        <option value="" className="text-databricks-ink">— pick one —</option>
        {items.map((w) => (
          <option key={w.id} value={w.id} className="text-databricks-ink">
            {w.name}
            {w.state ? ` · ${w.state}` : ''}
            {w.serverless ? ' · serverless' : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
