import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { SourcesPicker } from './SourcesPicker'

describe('SourcesPicker', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.history.replaceState(null, '', '/')
  })

  it('lists metric views from the API', async () => {
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
