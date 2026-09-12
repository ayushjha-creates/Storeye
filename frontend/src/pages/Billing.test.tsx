import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { BillingPage } from './Billing'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'
const CUSTOMER_ID = 'aaaabbbb-0000-4000-8000-000000000003'

const routes = {
  '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
  '/api/bills': {
    items: [
      {
        id: 'b1',
        store_id: STORE_ID,
        bill_number: 'BILL-001',
        sale_id: null,
        customer_id: null,
        subtotal: '100.00',
        tax_total: '5.00',
        total: '105.00',
        delivery_status: 'DRAFT',
        items: [],
      },
    ],
    total: 1,
  },
  '/api/products': {
    items: [
      { id: PRODUCT_ID, store_id: STORE_ID, sku: 'AMUL-1L', name: 'Amul Milk 1L', selling_price: '62.00', cost_price: '55.00', tax_rate: '0.05', is_active: true },
    ],
    total: 1,
  },
  '/api/customers': {
    items: [
      { id: CUSTOMER_ID, store_id: STORE_ID, mobile: '9876500000', name: 'Ravi Kumar' },
    ],
    total: 1,
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BillingPage', () => {
  it('lists existing manual bills and explains the no-AI-billing rule', async () => {
    stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('BILL-001')).toBeInTheDocument()
    expect(screen.getByText(/manual billing only/i)).toBeInTheDocument()
    expect(screen.getByText(/no AI-generated billing/i)).toBeInTheDocument()
    expect(screen.getByText('₹105.00')).toBeInTheDocument()
  })

  it('creates a manual bill and posts it to /api/bills', async () => {
    const fetchMock = stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /\+ new bill/i }))

    expect(screen.getByText(/create manual bill/i)).toBeInTheDocument()
    expect(screen.getByText(/amul milk 1l/i)).toBeInTheDocument() // auto-added line item

    await userEvent.click(screen.getByRole('button', { name: /save bill/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/bills'))).toBe(true)
  })
})