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
      {
        id: 'b2',
        store_id: STORE_ID,
        bill_number: 'BILL-002',
        sale_id: null,
        customer_id: CUSTOMER_ID,
        subtotal: '20.00',
        tax_total: '0.00',
        total: '20.00',
        delivery_status: 'DRAFT',
        items: [],
      },
    ],
    total: 2,
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
  '/api/sms/status': {
    enabled: true,
    provider: 'msg91',
    configured: true,
    counts: { total: 2, queued: 0, sending: 0, sent: 1, failed: 1 },
  },
  '/api/sms/messages': {
    items: [
      {
        id: 'm1',
        store_id: STORE_ID,
        bill_id: 'b2',
        customer_id: CUSTOMER_ID,
        mobile: '9876500000',
        message: 'Receipt for BILL-002',
        status: 'SENT',
        attempts: 1,
        last_error: null,
        next_attempt_at: null,
        sent_at: '2026-09-18T10:00:00Z',
        provider: 'msg91',
        created_at: '2026-09-18T10:00:00Z',
        updated_at: '2026-09-18T10:00:00Z',
      },
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
    expect(screen.getByText(/your bills for today/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /recent bills/i })).toBeInTheDocument()
    expect(screen.getByText('₹105.00')).toBeInTheDocument()
  })

  it('creates a manual bill and posts it to /api/bills', async () => {
    const fetchMock = stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /\+ new sale/i }))

    expect(screen.getByText(/create manual bill/i)).toBeInTheDocument()
    expect(screen.getByText(/amul milk 1l/i)).toBeInTheDocument() // auto-added line item

    await userEvent.click(screen.getByRole('button', { name: /save bill/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/bills'))).toBe(true)
  })

  it('shows receipt SMS delivery state and the on-banner when SMS is enabled', async () => {
    stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/receipt sms is on/i)).toBeInTheDocument()
    expect(screen.getByText(/sent 1/i)).toBeInTheDocument()
    // Walk-in bill has no phone -> no receipt; customer bill shows its Sent badge.
    expect(screen.getByText('Sent')).toBeInTheDocument()
    expect(screen.getByText('—').closest('tr')).not.toBeNull()
  })

  it('resends a failed SMS receipt from the bill row', async () => {
    const withFailure = {
      ...routes,
      '/api/sms/messages': {
        items: [
          {
            id: 'm2',
            store_id: STORE_ID,
            bill_id: 'b2',
            customer_id: CUSTOMER_ID,
            mobile: '9876500000',
            message: 'Receipt for BILL-002',
            status: 'FAILED',
            attempts: 5,
            last_error: 'HTTP 502: upstream',
            next_attempt_at: null,
            sent_at: null,
            provider: 'msg91',
            created_at: '2026-09-18T10:00:00Z',
            updated_at: '2026-09-18T11:00:00Z',
          },
        ],
        total: 1,
      },
    }
    const fetchMock = stubFetchRoutes(withFailure)
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    const resend = await screen.findByRole('button', { name: /resend/i })
    expect(screen.getByText('Failed')).toBeInTheDocument()
    await userEvent.click(resend)

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/sms/messages/m2/resend')),
    ).toBe(true)
  })

  it('hides the SMS banner when SMS delivery is disabled', async () => {
    stubFetchRoutes({
      ...routes,
      '/api/sms/status': {
        enabled: false,
        provider: 'msg91',
        configured: false,
        counts: { total: 0, queued: 0, sending: 0, sent: 0, failed: 0 },
      },
    })
    render(
      <MemoryRouter>
        <BillingPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('BILL-001')).toBeInTheDocument()
    expect(screen.queryByText(/receipt sms is on/i)).not.toBeInTheDocument()
  })
})