import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { JourneysPage } from './Journeys'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const SUMMARY = {
  total_visitors: 12,
  active_visitors: 2,
  avg_visit_duration_seconds: 780,
  avg_zone_dwell_seconds: 95,
  total_zone_visits: 31,
  most_visited_zone: { zone_id: 'z1', name: 'Snacks', visits: 9 },
}

const JOURNEY = {
  global_person_id: 'gp-alice-0001-0000000000000001',
  store_id: STORE_ID,
  status: 'active',
  confidence: 'HIGH',
  first_seen_at: '2026-09-10T10:00:00Z',
  last_seen_at: '2026-09-10T10:13:00Z',
  duration_seconds: 780,
  camera_count: 3,
  cameras_visited: [
    { camera_id: 'c1', name: 'Entrance' },
    { camera_id: 'c2', name: 'Aisle 4' },
    { camera_id: 'c3', name: 'Till' },
  ],
  zone_visits_total: 2,
  zones_visited: [
    { zone_id: 'z1', name: 'Snacks', visits: 2 },
    { zone_id: 'z2', name: 'Billing', visits: 1 },
  ],
}

function routes(overrides: Record<string, unknown> = {}) {
  return {
    '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
    '/api/journeys/summary': SUMMARY,
    '/api/journeys': { items: [JOURNEY], total: 1 },
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('JourneysPage', () => {
  it('renders KPIs and the journey list with opaque person ids', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <JourneysPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Total visitors')).toBeInTheDocument()
    expect(screen.getByText('in selected window')).toBeInTheDocument()
    expect(screen.getByText('Currently active')).toBeInTheDocument()
    expect(screen.getByText('shopping right now')).toBeInTheDocument()
    expect(screen.getAllByText('13m 0s').length).toBeGreaterThan(0)
    expect(screen.getByText('1m 35s')).toBeInTheDocument()

    // List row: opaque (short) id, status, confidence, camera/zone names.
    expect(screen.getByText(/gp-ali/)).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getAllByText('HIGH').length).toBeGreaterThan(0)
    expect(screen.getByText(/Entrance, Aisle 4/)).toBeInTheDocument()
    expect(screen.getByText(/Snacks ×2/)).toBeInTheDocument()
  })

  it('filters the list by confidence', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <JourneysPage />
      </MemoryRouter>,
    )

    await screen.findByText('Total visitors')
    const select = screen.getByLabelText(/Confidence/i)
    await userEvent.selectOptions(select, 'HIGH')
    expect(await screen.findAllByText('HIGH')).not.toHaveLength(0)
  })

  it('shows the empty state when no journeys exist', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/journeys/summary': {
        total_visitors: 0,
        active_visitors: 0,
        avg_visit_duration_seconds: null,
        avg_zone_dwell_seconds: null,
        total_zone_visits: 0,
        most_visited_zone: null,
      },
      '/api/journeys': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <JourneysPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/no journeys recorded yet/i)).toBeInTheDocument()
  })

  it('shows a retryable error when the backend is down', async () => {
    stubFetchReject()
    render(
      <MemoryRouter>
        <JourneysPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})