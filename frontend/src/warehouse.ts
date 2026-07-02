// Selected SQL warehouse persists in localStorage so the user picks it once.
// Sent as `X-Warehouse-Id` on every API call that needs it (see api.ts).

import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'dbx2pbi.warehouse_id'
const CHANGE_EVENT = 'dbx2pbi:warehouse-changed'

export function getWarehouseId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function setWarehouseId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id)
    else window.localStorage.removeItem(STORAGE_KEY)
    window.dispatchEvent(new Event(CHANGE_EVENT))
  } catch {
    // localStorage disabled — no-op
  }
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(CHANGE_EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

export function useWarehouseId(): string | null {
  return useSyncExternalStore(subscribe, getWarehouseId, () => null)
}

export function warehouseHeaders(): Record<string, string> {
  const id = getWarehouseId()
  return id ? { 'X-Warehouse-Id': id } : {}
}
