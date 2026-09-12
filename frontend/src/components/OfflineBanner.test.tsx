import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { OfflineBanner } from './OfflineBanner'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true })
})

describe('OfflineBanner', () => {
  it('renders nothing when the edge node AND internet are reachable', async () => {
    stubFetchRoutes({ '/api/health': { status: 'ok' }, '/api/ready': { ready: true, database: 'postgres', stores: 1 } })
    render(
      <EdgeProvider>
        <OfflineBanner />
      </EdgeProvider>,
    )
    await vi.waitFor(() => {
      expect(screen.queryByText(/edge node unreachable/i)).not.toBeInTheDocument()
    })
    expect(screen.queryByText(/internet offline/i)).not.toBeInTheDocument()
  })

  it('treats internet-down as NORMAL operation while the edge is online', async () => {
    stubFetchRoutes({ '/api/health': { status: 'ok' }, '/api/ready': { ready: true, database: 'postgres', stores: 1 } })
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false })
    render(
      <EdgeProvider>
        <OfflineBanner />
      </EdgeProvider>,
    )
    expect(await screen.findByText(/internet offline — storeye is running on the local edge node/i)).toBeInTheDocument()
    expect(screen.queryByText(/edge node unreachable/i)).not.toBeInTheDocument()
  })

  it('shows the degraded banner when the edge hub is unreachable', async () => {
    stubFetchReject()
    render(
      <EdgeProvider>
        <OfflineBanner />
      </EdgeProvider>,
    )
    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
  })
})