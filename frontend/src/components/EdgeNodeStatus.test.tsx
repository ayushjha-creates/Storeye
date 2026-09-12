import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { EdgeNodeStatus } from './EdgeNodeStatus'
import { stubFetchRoutes } from '../test/mock'

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true })
})

function edgeRoutes(runtime?: Record<string, unknown>) {
  return {
    '/api/health': { status: 'ok' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/edge/status':
      runtime ??
      ({
        status: 'online',
        offline: false,
        camera_count: 2,
        active_cameras: 2,
        frames_processed: 100,
        observations_written: 12,
        last_detection_at: '2026-09-06T10:00:00Z',
        models_loaded: ['person', 'shelf'],
        now: '2026-09-06T10:00:00Z',
      } as Record<string, unknown>),
  }
}

describe('EdgeNodeStatus', () => {
  it('shows an explicit EDGE MODE strip when internet is down but the edge node runs', async () => {
    stubFetchRoutes(edgeRoutes())
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false })
    render(
      <EdgeProvider>
        <EdgeNodeStatus />
      </EdgeProvider>,
    )

    expect(await screen.findByText(/edge mode/i)).toBeInTheDocument()
    // Real AI runtime counters from /api/edge/status.
    expect(screen.getByText('2/2')).toBeInTheDocument()
    expect(screen.getByText('person, shelf')).toBeInTheDocument()
  })

  it('does not claim AI is running when the runtime reports it is not', async () => {
    stubFetchRoutes(
      edgeRoutes({ ...edgeRoutes()['/api/edge/status'], offline: true, status: 'offline', active_cameras: 0 }),
    )
    render(
      <EdgeProvider>
        <EdgeNodeStatus />
      </EdgeProvider>,
    )

    expect(await screen.findByText('STOPPED')).toBeInTheDocument()
  })

  it('marks the AI runtime as CHECKING when the runtime status endpoint is unreachable', async () => {
    stubFetchRoutes({
      '/api/health': { status: 'ok' },
      '/api/ready': { ready: true, database: 'postgres', stores: 1 },
      '/api/edge/status': [500, { detail: 'down' }],
    })
    render(
      <EdgeProvider>
        <EdgeNodeStatus />
      </EdgeProvider>,
    )

    expect(await screen.findByText('CHECKING')).toBeInTheDocument()
  })
})