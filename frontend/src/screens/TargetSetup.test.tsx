import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { TargetSetup } from './TargetSetup'

describe('TargetSetup', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.history.replaceState(null, '', '/')
  })

  it('surfaces the backend error message and suggestion when workspace listing fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/fabric/workspaces')) {
        return new Response(
          JSON.stringify({
            code: 'fabric_sp_unauthorized',
            message: 'Fabric SP credentials were rejected by Azure AD.',
            suggestion:
              'Authentication failed: AADSTS7000222: The provided client secret keys are expired.',
            docs_link: null,
          }),
          { status: 502 },
        )
      }
      return new Response(JSON.stringify([]))
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <TargetSetup />
      </QueryClientProvider>,
    )

    // The specific backend cause must reach the user, not a generic banner.
    await waitFor(() => {
      expect(
        screen.getByText('Fabric SP credentials were rejected by Azure AD.'),
      ).toBeDefined()
    })
    expect(screen.getByText(/AADSTS7000222/)).toBeDefined()
  })
})
