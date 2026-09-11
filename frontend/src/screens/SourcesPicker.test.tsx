import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { SourcesPicker } from './SourcesPicker'

describe('SourcesPicker', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // This jsdom build ships a stub `localStorage` (a Proxy with no working
    // methods); the picker reads the selected warehouse from it, so replace it
    // with a working in-memory one.
    const store: Record<string, string> = {}
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => (k in store ? store[k] : null),
        setItem: (k: string, v: string) => {
          store[k] = String(v)
        },
        removeItem: (k: string) => {
          delete store[k]
        },
        clear: () => {
          for (const k of Object.keys(store)) delete store[k]
        },
      },
    })
    window.history.replaceState(null, '', '/')
  })

  it('lists metric views from the API', async () => {
    // The metric-view list is gated on a selected warehouse (localStorage) plus
    // a catalog + schema (URL params); set all three so the query fires.
    window.localStorage.setItem('dbx2pbi.warehouse_id', 'wh-1')
    window.history.replaceState(null, '', '/?catalog=main&schema=sales')

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/metric_views')) {
        return new Response(JSON.stringify([
          { fully_qualified_name: 'main.sales.orders_mv', owner: 'alice', description: 'Sales', updated_at: null },
        ]))
      }
      return new Response(JSON.stringify([]))
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <SourcesPicker />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('main.sales.orders_mv')).toBeDefined()
    })
  })
})
