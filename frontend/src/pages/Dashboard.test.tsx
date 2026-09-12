import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { AuthProvider } from '../auth/AuthContext'
import { DashboardPage } from './Dashboard'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'
const CAMERA_ID = 'aaaabbbb-0000-4000-8000-000000000003'

function dashboardRoutes() {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/stores': {
      items: [{ id: STORE_ID, name: 'Kiran General Store', city: 'Pune' }],
      total: 1,
    },
    '/api/cameras': {
      items: [
        {
          id: CAMERA_ID,
          store_id: STORE_ID,
          name: 'Front Counter',
          location: 'Entrance',
          camera_type: 'usb',
          is_active: true,
          config: {},
        },
      ],
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
    '/api/observations': { items: [], total: 0 },
    '/api/reconciliation': { items: [], total: 0 },
    '/api/inventory/batches': { items: [], total: 0 },
    '/api/inventory/stores/': {
      id: '0',
      store_id: STORE_ID,
      product_id: PRODUCT_ID,
      quantity: 24,
      reorder_level: 5,
      reorder_quantity: 20,
    },
    '/api/bills': { items: [], total: 0 },
    '/api/sales': { items: [], total: 0 },
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
  it('renders store name, live stats and the edge node card from real APIs', async () => {
    stubFetchRoutes(dashboardRoutes())
    renderDashboard()

    expect(await screen.findByRole('heading', { name: /kiran general store/i })).toBeInTheDocument()
    expect(screen.getByText('Total Products')).toBeInTheDocument()
    expect(screen.getByText('Current Stock')).toBeInTheDocument()
    expect(screen.getByText('AI Runtime')).toBeInTheDocument()
    expect(screen.getByText('1/1')).toBeInTheDocument() // active cameras 1/1
  })

  it('renders the empty states when there are no detections or alerts', async () => {
    stubFetchRoutes(dashboardRoutes())
    renderDashboard()

    expect(await screen.findByText(/no observations yet/i)).toBeInTheDocument()
    expect(screen.getByText(/no low-stock products right now/i)).toBeInTheDocument()
    expect(screen.getByText(/no reconciliation alerts/i)).toBeInTheDocument()
  })

  it('renders the Alerts card with open alert counts from the alert inbox', async () => {
    stubFetchRoutes({
      ...dashboardRoutes(),
      '/api/alerts': {
        items: [
          {
            id: '11111111-0000-4000-8000-000000000001',
            store_id: STORE_ID,
            camera_id: null,
            product_id: PRODUCT_ID,
            shelf_id: null,
            alert_type: 'SHORTAGE',
            severity: 'CRITICAL',
            status: 'OPEN',
            title: 'Possible shortage: Milk',
            message: 'AI sees 1 visible; inventory records 4.',
            confidence: 0.9,
            source_type: 'product_intelligence',
            source_id: null,
            first_detected_at: '2026-09-07T08:00:00Z',
            last_detected_at: '2026-09-07T08:05:00Z',
            acknowledged_at: null,
            resolved_at: null,
            dismissed_at: null,
            details: {},
            created_at: '2026-09-07T08:00:00Z',
            updated_at: '2026-09-07T08:05:00Z',
          },
        ],
        total: 1,
      },
    })
    renderDashboard()

    expect(await screen.findByText('Possible shortage: Milk')).toBeInTheDocument()

    const alertsCard = screen.getByText('High / Critical').closest('div')?.parentElement
      ?.parentElement as HTMLElement
    expect(within(alertsCard).getByText('Open')).toBeInTheDocument()
    expect(within(alertsCard).getAllByText('1').length).toBeGreaterThan(0)
    expect(within(alertsCard).getByText('CRITICAL')).toBeInTheDocument()
  })

  it('shows a degraded error banner description when the edge node is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderDashboard()

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByText(/storeye is edge-first/i)).toBeInTheDocument()
  })
})