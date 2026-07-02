// The catalog + schema the user is working in (chosen in the Sources picker)
// persist in localStorage so the History tab — a separate route — can scope run
// history to that namespace. Sent as X-History-Catalog / X-History-Schema on
// history API calls (see api.ts), matching where Apply writes the row.

import { useSyncExternalStore } from 'react'

const CATALOG_KEY = 'dbx2pbi.catalog'
const SCHEMA_KEY = 'dbx2pbi.schema'
const CHANGE_EVENT = 'dbx2pbi:namespace-changed'

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value) window.localStorage.setItem(key, value)
    else window.localStorage.removeItem(key)
    window.dispatchEvent(new Event(CHANGE_EVENT))
  } catch {
    // localStorage disabled — no-op
  }
}

export function getSelectedCatalog(): string | null {
  return read(CATALOG_KEY)
}

export function setSelectedCatalog(catalog: string | null): void {
  write(CATALOG_KEY, catalog)
}

export function getSelectedSchema(): string | null {
  return read(SCHEMA_KEY)
}

export function setSelectedSchema(schema: string | null): void {
  write(SCHEMA_KEY, schema)
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(CHANGE_EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

export function useSelectedCatalog(): string | null {
  return useSyncExternalStore(subscribe, getSelectedCatalog, () => null)
}

export function useSelectedSchema(): string | null {
  return useSyncExternalStore(subscribe, getSelectedSchema, () => null)
}

export function historyHeaders(): Record<string, string> {
  const catalog = getSelectedCatalog()
  const schema = getSelectedSchema()
  const headers: Record<string, string> = {}
  if (catalog) headers['X-History-Catalog'] = catalog
  if (schema) headers['X-History-Schema'] = schema
  return headers
}
