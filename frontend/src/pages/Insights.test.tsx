import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { InsightsPage } from './Insights'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const INSIGHT_LOW_STOCK = {
  id: '11111111-0000-4000-8000-000000000001',
  store_id: STORE_ID,
  category: 'inventory',
  insight_type: 'LOW_STOCK',
  severity: 'HIGH',
  status: 'OPEN',
  title: 'Milk (A-1): current stock below reorder level',
  description: 'Current stock 3 units is at or below the reorder level of 5.',
  rule_id: 'inventory.low_stock',
  source_modules: ['inventory'],
  evidence: {
    rule: 'inventory.low_stock',
    summary: ['Milk (A-1): current stock 3 units (reorder level: 5).'],
    sources: [{ source: 'inventory', entity_type: 'product', entity_name: null }],
    metrics: { current_stock: 3, reorder_level: 5 },
  },
  recommended_action: 'Restock Milk (A-1) to at least 20 units.',
  certainty: 'HIGH',
  entity_type: 'product',
  entity_id: 'p1',
  product_id: 'p1',
  shelf_id: 'aabbbbbb-0000-4000-8000-000000000001',
  zone_id: null,
  camera_id: null,
  first_detected_at: '2026-09-16T08:00:00Z',
  last_detected_at: '2026-09-16T08:05:00Z',
  expires_at: '2026-09-18T08:00:00Z',
  acknowledged_at: null,
  resolved_at: null,
  expired_at: null,
  created_at: '2026-09-16T08:00:00Z',
  updated_at: '2026-09-16T08:05:00Z',
}

const INSIGHT_EXPIRY = {
  ...INSIGHT_LOW_STOCK,
  id: '22222222-0000-4000-8000-000000000002',
  category: 'expiry',
  insight_type: 'EXPIRY_RISK',
  severity: 'MEDIUM',
  title: 'Batches expiring within 30 days',
  rule_id: 'expiry.expiring_soon',
  entity_type: 'batch',
  entity_id: 'b1',
  product_id: 'p2',
  shelf_id: null,
  evidence: {
    rule: 'expiry.expiring_soon',
    summary: ['Batch AAS-1 expires 2026-10-05 (29 days).'],
    sources: [{ source: 'batch', entity_type: 'batch', entity_name: null }],
    metrics: { batch_number: 'AAS-1', days_until_expiry: 29 },
  },
  recommended_action: 'Rotate stock: move AAS-1 to the front of the shelf.',
  certainty: 'MEDIUM',
}

const SUMMARY = {
  store_id: STORE_ID,
  total: 21,
  open: 6,
  acknowledged: 1,
  high_priority: 3,
  inventory: 5,
  shelf: 4,
  expiry: 3,
  customer_flow: 4,
  camera: 3,
  store_health: 1,
  by_type: { inventory: 5, shelf: 4, expiry: 3, customer_flow: 4, camera: 3, store_health: 1 },
  by_severity: { HIGH: 3, MEDIUM: 4, LOW: 4 },
}

const HEALTH = {
  store_id: STORE_ID,
  state: 'CRITICAL',
  basis: ['Out of stock: Bread (HIGH)', 'Expired batch: Milk (CRITICAL)'],
  cameras: { total: 5, offline: 1 },
  inventory: { total: 14, low: 2, out_of_stock: 1 },
  shelf: { known: 5, low_or_empty: 1 },
  alerts: { open: 2 },
  expiry: { expired: 1, expiring_soon: 2 },
  customer_flow: { visitors: 120, active: 4 },
  edge: { online: 4, offline_cameras: 1 },
  evaluated_at: '2026-09-17T09:00:00Z',
}

function routes(overrides: Record<string, unknown> = {}) {
  return {
    '/api/insights/evaluate': {
      evaluated_at: '2026-09-17T09:00:00Z',
      store_id: STORE_ID,
      candidates: 15,
      created: 0,
      refreshed: 8,
      resolved: 0,
      expired: 0,
      alerts_created: 1,
      alerts_updated: 0,
      insights: [INSIGHT_LOW_STOCK, INSIGHT_EXPIRY],
    },
    '/api/insights/summary': SUMMARY,
    '/api/insights/store-health': HEALTH,
    '/api/insights': { items: [INSIGHT_LOW_STOCK, INSIGHT_EXPIRY], total: 2 },
    '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InsightsPage', () => {
  it('renders KPIs, the store health card and the insight list', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /insights/i })).toBeInTheDocument()
    expect(screen.getByText('store-wide')).toBeInTheDocument()
    expect(screen.getByText('needs attention')).toBeInTheDocument()
    expect(screen.getByText('reviewed, not yet cleared')).toBeInTheDocument()
    expect(screen.getByText('active HIGH/CRITICAL')).toBeInTheDocument()
    expect(screen.getAllByText('Store health').length).toBeGreaterThan(0)
    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
    expect(screen.getByText(/out of stock: bread/i)).toBeInTheDocument()
    expect(screen.getByText(/current stock below reorder level/i)).toBeInTheDocument()
    expect(screen.getByText(/batches expiring within 30 days/i)).toBeInTheDocument()
    expect(screen.getByText(/low stock/i)).toBeInTheDocument()
    expect(screen.getAllByText('OPEN').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /evaluate now/i })).toBeInTheDocument()
  })

  it('opens the evidence panel with summary, metrics, action and privacy note', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    const rows = await screen.findAllByText(/current stock below reorder level/i)
    await userEvent.click(rows[0])

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/reorder level: 5/i)).toBeInTheDocument()
    expect(screen.getByText('current_stock')).toBeInTheDocument()
    expect(screen.getByText(/restock milk/i)).toBeInTheDocument()
    expect(screen.getByText(/never auto-adjusts inventory/i)).toBeInTheDocument()
  })

  it('acknowledges an insight through the lifecycle endpoint', async () => {
    const fetchMock = stubFetchRoutes(
      routes({
        '/acknowledge': {
          ...INSIGHT_LOW_STOCK,
          status: 'ACKNOWLEDGED',
          acknowledged_at: '2026-09-17T09:30:00Z',
        },
      }),
    )
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    const acknowledgeButtons = await screen.findAllByRole('button', { name: /acknowledge/i })
    await userEvent.click(acknowledgeButtons[0])

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes(`${INSIGHT_LOW_STOCK.id}/acknowledge`)),
    ).toBe(true)
    expect(await screen.findByText('ACKNOWLEDGED')).toBeInTheDocument()
  })

  it('runs the evaluate endpoint and refreshes the list', async () => {
    const fetchMock = stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /evaluate now/i }))

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/insights/evaluate')),
    ).toBe(true)
    expect(await screen.findByRole('heading', { name: /insights/i })).toBeInTheDocument()
  })

  it('filters by category and status via query params', async () => {
    const fetchMock = stubFetchRoutes(
      routes({
        'category=customer_flow': {
          items: [],
          total: 0,
        },
      }),
    )
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    await screen.findByRole('heading', { name: /insights/i })
    await userEvent.selectOptions(screen.getByLabelText(/filter by category/i), 'customer_flow')

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('category=customer_flow')),
    ).toBe(true)
  })

  it('shows the empty state when evaluation finds no insights', async () => {
    stubFetchRoutes(
      routes({
        '/api/insights/summary': { ...SUMMARY, total: 0, open: 0, acknowledged: 0, high_priority: 0 },
        '/api/insights/store-health': { ...HEALTH, state: 'HEALTHY', basis: [] },
        '/api/insights': { items: [], total: 0 },
      }),
    )
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/no insights yet/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /evaluate now/i })).toBeInTheDocument()
    expect(screen.getAllByText('HEALTHY').length).toBeGreaterThan(0)
  })

  it('shows a retryable error when the backend is down', async () => {
    stubFetchReject()
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})