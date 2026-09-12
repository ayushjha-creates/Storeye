import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { AuthProvider } from '../auth/AuthContext'
import { ReportsPage } from './Reports'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'

function reportsRoutes() {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/stores': { items: [{ id: STORE_ID, name: 'Kiran General Store' }], total: 1 },
    '/api/sales': {
      items: [
        {
          id: '11111111-0000-4000-8000-000000000001',
          store_id: STORE_ID,
          sale_timestamp_utc: new Date().toISOString(),
          subtotal: '100.00',
          tax_total: '0.00',
          total: '100.00',
          payment_method: 'CASH',
          customer_id: null,
          items: [
            { id: 'a', sale_id: '11111111-0000-4000-8000-000000000001', product_id: PRODUCT_ID, quantity: 2, unit_price: '50.00', tax: '0', line_total: '100.00' },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    },
    '/api/bills': {
      items: [
        {
          id: '22222222-0000-4000-8000-000000000002',
          store_id: STORE_ID,
          bill_number: 'DEMO-BILL-0001',
          sale_id: null,
          customer_id: null,
          subtotal: '100.00',
          tax_total: '0.00',
          total: '100.00',
          delivery_status: 'DELIVERED',
          items: [
            { id: 'b', bill_id: '22222222-0000-4000-8000-000000000002', product_id: PRODUCT_ID, quantity: 2, unit_price: '50.00', tax: '0', line_total: '100.00' },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    },
    '/api/products': { items: [{ id: PRODUCT_ID, name: 'Amul Milk 1L' }], total: 1 },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReportsPage', () => {
  it('renders KPIs and recent bills from real sales records', async () => {
    stubFetchRoutes(reportsRoutes())
    render(
      <AuthProvider>
        <EdgeProvider>
          <MemoryRouter>
            <ReportsPage />
          </MemoryRouter>
        </EdgeProvider>
      </AuthProvider>,
    )

    expect(await screen.findByRole('heading', { name: /reports & analytics/i })).toBeInTheDocument()
    expect(screen.getByText('Revenue · 30d')).toBeInTheDocument()
    expect(screen.getByText('BILL-0001')).toBeInTheDocument()
    expect(screen.getByText(/sale record\(s\) on file/i)).toBeInTheDocument()
  })
})