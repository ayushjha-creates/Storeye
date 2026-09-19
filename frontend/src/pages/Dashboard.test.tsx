import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { AuthProvider } from '../auth/AuthContext'
import { DashboardPage } from './Dashboard'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'

function daily() {
  const out: { date: string; visitors: number }[] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    out.push({ date: d.toISOString().slice(0, 10), visitors: 3 + i })
  }
  return out
}

function dashboardRoutes() {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/auth/me': {
      id: 'aaaaaaaa-0000-4000-8000-000000000000',
      email: 'owner@storeye.local',
      name: 'Kiran Owner',
      role: 'OWNER',
      store_id: STORE_ID,
      is_active: true,
      last_login_at: null,
      created_at: '2026-01-01T00:00:00Z',
      store_name: 'Kiran General Store',
      demo_store: false,
    },
    '/api/stores': {
      items: [{ id: STORE_ID, name: 'Kiran General Store', city: 'Pune' }],
      total: 1,
    },
    '/api/products': {
      items: [
        {
          id: PRODUCT_ID,
          store_id: STORE_ID,
          sku: 'AMUL-1L',
          name: 'Amul Milk 1L',
          brand: 'Amul',
          category: 'Dairy',
          unit: 'packet',
          selling_price: '62.00',
          cost_price: '55.00',
          tax_rate: '0.05',
          is_active: true,
        },
      ],
      total: 1,
    },
    '/api/inventory/stores/': {
      id: '0',
      store_id: STORE_ID,
      product_id: PRODUCT_ID,
      quantity: 24,
      reorder_level: 5,
      reorder_quantity: 20,
    },
    '/api/inventory/batches': { items: [], total: 0 },
    '/api/bills': { items: [], total: 0 },
    '/api/sales': { items: [], total: 0 },
    '/api/intelligence/summary': {
      computed_at: new Date().toISOString(),
      window_hours: 24,
      cameras: { online: 1, offline: 0 },
      people: { total_person_sessions: 12 },
      products: { visible_classes: 4, total_detections: 20 },
      shelves: { regions_configured: 2, low_visible: 1, empty_visible: 0, unmonitored: 0 },
      reconciliation: { total: 1, matched: 1, discrepancies: 0, unknown_mismatches: 0 },
    },
    '/api/journeys/daily': { items: daily(), total: 7 },
    '/api/journeys/summary': {
      total_visitors: 12,
      active_visitors: 1,
      avg_visit_duration_seconds: 95,
      avg_zone_dwell_seconds: 21,
      total_zone_visits: 9,
      most_visited_zone: null,
    },
    '/api/mobile-intake/jobs': { items: [], total: 0 },
    '/api/edge/cameras': [
      {
        camera_id: 'b000',
        running: true,
        health: 'RUNNING',
        capture_fps: 24,
        inference_fps: 12.4,
        inference_ms: 21,
        last_frame_age_seconds: 0.05,
        observations_written: 42,
        started_at: new Date().toISOString(),
        last_frame_at: new Date().toISOString(),
      },
    ],
  }
}

function renderDashboard() {
  render(
    <AuthProvider>
      <EdgeProvider>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </EdgeProvider>
    </AuthProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DashboardPage', () => {
  it('renders the shopkeeper Home with real KPIs, attention and footfall chart', async () => {
    stubFetchRoutes(dashboardRoutes())
    renderDashboard()

    expect(await screen.findByText(/kiran general store/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /today's sales/i })).toBeInTheDocument()
    expect(screen.getByText(/current stock/i)).toBeInTheDocument()
    expect(screen.getByText(/running low/i)).toBeInTheDocument()
    expect(screen.getByText(/what needs your attention/i)).toBeInTheDocument()
    expect(screen.getByText(/receive stock/i)).toBeInTheDocument()

    // 12 visitors from the 24h journey summary surface in the activity card.
    expect(await screen.findByText('12')).toBeInTheDocument()

    // Footfall: 7 days with 9+8+7+6+5+4+3 = 42 visitors.
    expect(screen.getByText('42 visitors counted over 7 days')).toBeInTheDocument()
    expect(screen.getByText(/counted by your cameras/i)).toBeInTheDocument()
  })

  it('renders honest empty states when there is no footfall or recent receipts', async () => {
    stubFetchRoutes({
      ...dashboardRoutes(),
      '/api/journeys/daily': { items: [], total: 0 },
      '/api/intelligence/summary': {
        ...dashboardRoutes()['/api/intelligence/summary'] as object,
        shelves: { regions_configured: 2, low_visible: 0, empty_visible: 0, unmonitored: 0 },
      },
    })
    renderDashboard()

    expect(await screen.findByText(/no footfall recorded yet/i)).toBeInTheDocument()
    expect(screen.getByText(/no stock receipts waiting/i)).toBeInTheDocument()
    expect(screen.getByText(/nothing needs your attention right now/i)).toBeInTheDocument()
  })

  it('lists the real issues under "What needs your attention" from live data', async () => {
    stubFetchRoutes({
      ...dashboardRoutes(),
      '/api/inventory/stores/': {
        id: '0',
        store_id: STORE_ID,
        product_id: PRODUCT_ID,
        quantity: 0,
        reorder_level: 5,
        reorder_quantity: 20,
      },
    })
    renderDashboard()

    expect(await screen.findByText(/1 product is out of stock/i)).toBeInTheDocument()
  })

  it('shows "Offline mode" when the Edge hub is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderDashboard()

    expect(await screen.findByText(/offline mode — data still on this computer/i))
      .toBeInTheDocument()
  })
})