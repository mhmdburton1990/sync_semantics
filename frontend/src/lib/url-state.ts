import { useCallback, useSyncExternalStore } from 'react'

function subscribe(cb: () => void): () => void {
  window.addEventListener('popstate', cb)
  return () => window.removeEventListener('popstate', cb)
}

function getSnapshot(): string {
  return window.location.search
}

// Reactive current query string — re-renders subscribers when it changes,
// including in-place pushState updates (which dispatch a popstate event).
export function useUrlSearch(): string {
  return useSyncExternalStore(subscribe, getSnapshot, () => '')
}

// Write the query string in place and notify subscribers. These are selection
// updates (a checkbox, a dropdown), NOT navigations, so we preserve the scroll
// position — the synthetic popstate would otherwise jump the page to the top.
function writeSearch(mutate: (p: URLSearchParams) => void): void {
  const p = new URLSearchParams(window.location.search)
  mutate(p)
  const qs = p.toString()
  const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname
  const y = window.scrollY
  window.history.pushState(null, '', url)
  window.dispatchEvent(new PopStateEvent('popstate'))
  if (window.scrollY !== y) window.scrollTo(0, y)
  requestAnimationFrame(() => {
    if (window.scrollY !== y) window.scrollTo(0, y)
  })
}

export function useUrlParam<T extends string>(
  key: string,
  defaultValue: T,
): [T, (v: T) => void] {
  const search = useSyncExternalStore(subscribe, getSnapshot, () => '')
  const params = new URLSearchParams(search)
  const value = (params.get(key) ?? defaultValue) as T

  const set = useCallback(
    (v: T) => writeSearch((p) => p.set(key, v)),
    [key],
  )

  return [value, set]
}

export function useUrlList(key: string): [string[], (v: string[]) => void] {
  const search = useSyncExternalStore(subscribe, getSnapshot, () => '')
  const params = new URLSearchParams(search)
  const raw = params.get(key)
  const value = raw ? raw.split(',').filter(Boolean) : []

  const set = useCallback(
    (v: string[]) =>
      writeSearch((p) => (v.length === 0 ? p.delete(key) : p.set(key, v.join(',')))),
    [key],
  )

  return [value, set]
}
