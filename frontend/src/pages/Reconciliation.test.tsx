import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { ReconciliationPage } from './Reconciliation'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_A = 'aaaabbbb-0000-4000-8000-000000000002'
const PRODUCT_B = 'aaaabbbb-0000-4000-8000-000000000003'

const RESULTS = [
  {
    id: 'r1',
    store_id: STORE_ID,
    product_id: PRODUCT_A,
    camera_id: null,
    observation_window_start: '2026-09-05T10:00:00Z',
    observation_window_end: '2026-09-06T10:00:00Z',
    database_quantity: 20,
    ai_observed_quantity: 18,
    difference: -2,
    status: 'POSSIBLE_SHORTAGE',
    confidence: 0.9,
    details: null,
    created_at: '2026-09-06T10:05:00Z',
  },
  {
    id: 'r2',
    store_id: STORE_ID,
    product_id: PRODUCT_B,
    camera_id: null,
    observation_window_start: '2026-09-05T10:00:00Z',
    observation_window_end: '2026-09-06T10:00:00Z',
    database_quantity: 10,
    ai_observed_quantity: 10,
    difference: 0,
    status: 'MATCH',
    confidence: 0.95,
    details: null,
    created_at: '2026-09-06T10:06:00Z',
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReconciliationPage', () => {
  it('renders informational status badges and the products involved', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/reconciliation': { items: RESULTS, total: 2 },
      '/api/products': {
        items: [
          { id: PRODUCT_A, store_id: STORE_ID, sku: 'A1', name: 'Cola 1L', selling_price: '50.00', tax_rate: '0.12', is_active: true },
          { id: PRODUCT_B, store_id: STORE_ID, sku: 'B1', name: 'Rice 5kg', selling_price: '320.00', tax_rate: '0.05', is_active: true },
        ],
        total: 2,
      },
    })
    render(
      <MemoryRouter>
        <ReconciliationPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /reconciliation/i })).toBeInTheDocument()
    expect(screen.getByText(/informational only/i)).toBeInTheDocument()
    expect(screen.getAllByText('POSSIBLE_SHORTAGE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MATCH').length).toBeGreaterThan(0)
    expect(screen.getByText('Cola 1L')).toBeInTheDocument()
    expect(screen.getByText('Rice 5kg')).toBeInTheDocument()
  })

  it('runs a new reconciliation through the API', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/reconciliation': { items: RESULTS, total: 2 },
      '/api/products': { items: [], total: 0 },
      '/api/reconciliation/run': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <ReconciliationPage />
      </MemoryRouter>,
    )

    const runButton = await screen.findByRole('button', { name: /run reconciliation/i })
    await userEvent.click(runButton)

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/reconciliation/run'))).toBe(true)
  })
})