import { useEffect, useState } from 'react'
import { authHeaders } from '../auth'
import { warehouseHeaders } from '../warehouse'

export interface SseEvent { name: string; data: string }

export function useSse(
  url: string | null,
  body: unknown,
): { events: SseEvent[]; done: boolean; error: string | null } {
  const [events, setEvents] = useState<SseEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!url) return
    const ctrl = new AbortController()

    async function run(): Promise<void> {
      try {
        const resp = await fetch(url!, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders(),
            ...warehouseHeaders(),
          },
          body: JSON.stringify(body),
          signal: ctrl.signal,
        })
        if (!resp.ok || !resp.body) {
          setError(`HTTP ${resp.status}`)
          return
        }
        const reader = resp.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        let currentName = 'message'
        while (true) {
          const { done: rdone, value } = await reader.read()
          if (rdone) break
          buf += dec.decode(value, { stream: true })
          let idx
          while ((idx = buf.indexOf('\n')) !== -1) {
            const line = buf.slice(0, idx).trim()
            buf = buf.slice(idx + 1)
            if (line.startsWith('event:')) currentName = line.slice(6).trim()
            else if (line.startsWith('data:')) {
              setEvents((prev) => [...prev, { name: currentName, data: line.slice(5).trim() }])
              if (currentName === 'done') setDone(true)
            }
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) setError(String(e))
      }
    }
    void run()
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  return { events, done, error }
}
