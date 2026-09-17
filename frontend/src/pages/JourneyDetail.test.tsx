import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { JourneyDetailPage } from './JourneyDetail'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const GID = 'gp-alice-0001-0000000000000001'

const DETAIL = {
  global_person_id: GID,
  store_id: STORE_ID,
  status: 'expired',
  confidence: 'MEDIUM',
  first_seen_at: '2026-09-10T10:00:00Z',
  last_seen_at: '2026-09-10T10:22:30Z',
  duration_seconds: 1350,
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
  track_associations: [
    {
      camera_id: 'c1',
      camera_name: 'Entrance',
      track_id: 3,
      started_at: '2026-09-10T10:00:00Z',
      ended_at: '2026-09-10T10:04:00Z',
      last_seen_at: '2026-09-10T10:04:00Z',
      confidence: 'HIGH',
    },
  ],
  zone_visits: [
    {
      zone_id: 'z1',
      zone_name: 'Snacks',
      camera_id: 'c2',
      camera_name: 'Aisle 4',
      entered_at: '2026-09-10T10:05:00Z',
      exited_at: '2026-09-10T10:12:00Z',
      dwell_seconds: 420,
      confidence: 'MEDIUM',
    },
    {
      zone_id: 'z2',
      zone_name: 'Billing',
      camera_id: 'c3',
      camera_name: 'Till',
      entered_at: '2026-09-10T10:18:00Z',
      exited_at: null,
      dwell_seconds: null,
      confidence: 'MEDIUM',
    },
  ],
  transitions: [
    {
      from_camera_id: 'c1',
      from_camera_name: 'Entrance',
      to_camera_id: 'c2',
      to_camera_name: 'Aisle 4',
      transitioned_at: '2026-09-10T10:04:00Z',
      time_gap_seconds: 12,
      confidence: 'HIGH',
    },
  ],
  timeline: [
    {
      at: '2026-09-10T10:00:00Z',
      type: 'journey_start',
      camera_id: 'c1',
      camera_name: 'Entrance',
      zone_id: null,
      zone_name: null,
      detail: 'Shopper entered the store at the entrance',
    },
    {
      at: '2026-09-10T10:05:00Z',
      type: 'zone_enter',
      camera_id: 'c2',
      camera_name: 'Aisle 4',
      zone_id: 'z1',
      zone_name: 'Snacks',
      detail: 'Shopper dwelled in the Snacks zone',
    },
  ],
}

function renderDetail(gid = GID) {
  stubFetchRoutes({
    '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
    [`/api/journeys/${gid}`]: DETAIL,
  })
  return render(
    <MemoryRouter initialEntries={[`/journeys/${gid}`]}>
      <Routes>
        <Route path="/journeys/:journeyId" element={<JourneyDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('JourneyDetailPage', () => {
  it('renders KPIs, timeline, zone visits and transitions', async () => {
    renderDetail()

    expect(await screen.findByText(/gp-ali/)).toBeInTheDocument()
    expect(screen.getByText('EXPIRED')).toBeInTheDocument()
    expect(screen.getAllByText('MEDIUM').length).toBeGreaterThan(0)

    // KPIs: string values + hints render directly (numeric values animate).
    expect(screen.getByText('Duration')).toBeInTheDocument()
    expect(screen.getAllByText('22m 30s').length).toBeGreaterThan(0)
    expect(screen.getByText('Cameras')).toBeInTheDocument()
    expect(screen.getByText('Entrance, Aisle 4, Till')).toBeInTheDocument()
    expect(screen.getAllByText('Zone visits').length).toBeGreaterThan(0)
    expect(screen.getByText('Track associations')).toBeInTheDocument()

    // Timeline.
    expect(screen.getByText(/journey start/i)).toBeInTheDocument()
    expect(screen.getByText(/shopper entered the store/i)).toBeInTheDocument()
    expect(screen.getByText(/zone enter/i)).toBeInTheDocument()

    // Zone visits (closed + still open).
    expect(screen.getByText('Snacks')).toBeInTheDocument()
    expect(screen.getAllByText(/7m 0s/).length).toBeGreaterThan(0)
    expect(screen.getByText(/still inside/i)).toBeInTheDocument()

    // Camera transitions.
    expect(screen.getByText('Entrance')).toBeInTheDocument()
    expect(screen.getByText('Aisle 4')).toBeInTheDocument()
  })

  it('shows a retryable error state when the journey cannot be loaded', async () => {
    stubFetchReject()
    render(
      <MemoryRouter initialEntries={[`/journeys/${GID}`]}>
        <Routes>
          <Route path="/journeys/:journeyId" element={<JourneyDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('shows an error when the journey is not found', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/journeys/gp-missing': [404, { detail: 'Journey not found' }],
    })
    render(
      <MemoryRouter initialEntries={[`/journeys/gp-missing`]}>
        <Routes>
          <Route path="/journeys/:journeyId" element={<JourneyDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/journey not found/i)).toBeInTheDocument()
  })
})