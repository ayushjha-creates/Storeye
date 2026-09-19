import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { InventoryPage } from './Inventory'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'

const routes = {
  '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
  '/api/products': {
    items: [
      { id: PRODUCT_ID, store_id: STORE_ID, sku: 'AMUL-1L', name: 'Amul Milk 1L', selling_price: '62.00', cost_price: '55.00', tax_rate: '0.05', is_active: true },
    ],
    total: 1,
  },
  '/api/inventory/batches': { items: [], total: 0 },
  '/api/inventory/stores/aaaabbbb-0000-4000-8000-000000000001/products/aaaabbbb-0000-4000-8000-000000000002/batches': {
    items: [], total: 0,
  },
  '/api/inventory/stores/aaaabbbb-0000-4000-8000-000000000001/products/aaaabbbb-0000-4000-8000-000000000002/movements': {
    items: [], total: 0,
  },
  '/api/inventory/stores/': {
    id: '0',
    store_id: STORE_ID,
    product_id: PRODUCT_ID,
    quantity: 24,
    reorder_level: 5,
    reorder_quantity: 20,
    created_at: '2026-09-06T00:00:00Z',
    updated_at: '2026-09-06T00:00:00Z',
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InventoryPage', () => {
  it('lists products and opens the stock detail drawer', async () => {
    stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <InventoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Amul Milk 1L')).toBeInTheDocument()
    expect(screen.getByText('AMUL-1L')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByText(/stock details/i)).toBeInTheDocument()
    expect(screen.getByText('+ Receive stock')).toBeInTheDocument()
    expect(screen.getByText(/movement history/i)).toBeInTheDocument()
  })

  it('submits a receive-stock mutation via POST /api/inventory/receive', async () => {
    const fetchMock = stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <InventoryPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /details/i }))
    await userEvent.click(screen.getByRole('button', { name: '+ Receive stock' }))

    const dialog = screen.getByRole('dialog', { name: /receive stock/i })
    const quantity = within(dialog).getByLabelText('Quantity to receive')
    await userEvent.clear(quantity)
    await userEvent.type(quantity, '10')
    await userEvent.click(within(dialog).getByRole('button', { name: /receive stock/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/inventory/receive'))).toBe(true)
  })
})