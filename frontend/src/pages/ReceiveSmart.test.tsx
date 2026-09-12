import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ReceiveSmartPage } from './ReceiveSmart'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'

const routes = {
  '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
  '/api/products': {
    items: [
      { id: PRODUCT_ID, store_id: STORE_ID, sku: 'AMUL-1L', name: 'Amul Milk 1L', selling_price: '62.00', tax_rate: '0.05', is_active: true },
      { id: 'aaaabbbb-0000-4000-8000-000000000003', store_id: STORE_ID, sku: 'GOLD-50', name: 'Gold Biscuit 50g', selling_price: '14.00', tax_rate: '0.05', is_active: true },
    ],
    total: 2,
  },
  '/api/batch-intake/scan': {
    store_id: STORE_ID,
    acceptable: true,
    reason: 'Barcode matched Amul Milk 1L.',
    candidate: {
      barcode_read: true,
      barcode: '8901234567890',
      product_id: PRODUCT_ID,
      product_name: 'Amul Milk 1L',
      product_sku: 'AMUL-1L',
      product_found: true,
      batch_number: 'M24031',
      manufacturing_date: '2026-03-12',
      expiry_date: '2026-12-15',
      expiry_date_precision: 'day',
      mrp: '14.00',
      confidence: 0.92,
      labels_found: ['exp', 'mfg', 'batch', 'mrp'],
      warnings: [],
    },
  },
  '/api/batch-intake/confirm': {
    movement: {
      id: 'mov-1',
      store_id: STORE_ID,
      product_id: PRODUCT_ID,
      movement_type: 'PURCHASE',
      quantity: 12,
      reference: null,
      created_at: '2026-09-09T10:00:00Z',
    },
    batch: {
      id: 'bat-1',
      store_id: STORE_ID,
      product_id: PRODUCT_ID,
      batch_number: 'M24031',
      manufacturing_date: '2026-03-12',
      expiry_date: '2026-12-15',
      expiry_date_precision: 'day',
      mrp: '14.00',
      quantity: 12,
      created_at: '2026-09-09T10:00:00Z',
      updated_at: '2026-09-09T10:00:00Z',
    },
  },
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:mock://pack.jpg') as unknown as typeof URL.createObjectURL
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function packImage(): File {
  return new File(['fake-image-bytes'], 'pack.jpg', { type: 'image/jpeg' })
}

// The scan response has the product already resolved, so the "Product"
// combobox is hidden behind the candidate — but it is always rendered as a
// select. We reach it by its accessible label.
function productSelect(): HTMLElement {
  const field = screen.getByLabelText('Product')
  const select = field.closest('label')?.querySelector('select')
  if (!select) throw new Error('Product select not found')
  return select as HTMLElement
}

describe('ReceiveSmartPage', () => {
  it('walks capture → scan → review → confirm → committed receipt', async () => {
    const fetchMock = stubFetchRoutes(routes)
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    await screen.findByText('Smart Batch Receiving')

    const input = screen.getByTestId('package-file-input') as HTMLInputElement
    await userEvent.upload(input, packImage())
    await userEvent.click(screen.getByRole('button', { name: /scan package/i }))

    // Scan result prefills the editable form.
    expect(await screen.findByText(/Barcode matched Amul Milk 1L/i)).toBeInTheDocument()
    expect(productSelect()).toHaveValue(PRODUCT_ID)
    expect(screen.getByLabelText('Batch number')).toHaveValue('M24031')
    expect(screen.getByLabelText('Expiry date')).toHaveValue('2026-12-15')

    // User edits a field and enters quantity, then confirms.
    const quantity = screen.getByLabelText(/Quantity to receive/)
    await userEvent.type(quantity, '12')
    const confirm = screen.getByRole('button', { name: /confirm receipt/i })
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)

    expect(await screen.findByText('Stock received')).toBeInTheDocument()
    expect(screen.getByText('M24031')).toBeInTheDocument()

    const posts = fetchMock.mock.calls.filter((c) => String(c[1]?.method ?? '').toUpperCase() === 'POST')
    expect(posts.some((c) => String(c[0]).includes('/api/batch-intake/scan'))).toBe(true)
    expect(posts.some((c) => String(c[0]).includes('/api/batch-intake/confirm'))).toBe(true)
    expect(posts.some((c) => String(c[0]).includes('/api/inventory/receive'))).toBe(false)
  })

  it('unknown barcode → manual fallback with product select required before confirm', async () => {
    stubFetchRoutes({
      ...routes,
      '/api/batch-intake/scan': {
        store_id: STORE_ID,
        acceptable: false,
        reason: 'Unable to confidently read package information.',
        candidate: {
          barcode_read: false,
          barcode: null,
          product_id: null,
          product_name: null,
          product_sku: null,
          product_found: false,
          batch_number: null,
          manufacturing_date: null,
          expiry_date: null,
          expiry_date_precision: 'day',
          mrp: null,
          confidence: null,
          labels_found: [],
          warnings: ['No barcode decoded.'],
        },
      },
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    const input = screen.getByTestId('package-file-input') as HTMLInputElement
    await userEvent.upload(input, packImage())
    await userEvent.click(screen.getByRole('button', { name: /scan package/i }))

    expect(await screen.findByText(/Unable to confidently read package information/i)).toBeInTheDocument()
    expect(productSelect()).toHaveValue('')
    expect(screen.getByRole('button', { name: /confirm receipt/i })).toBeDisabled()

    // Choose an existing product + quantity → confirm becomes available.
    await userEvent.selectOptions(productSelect(), PRODUCT_ID)
    await userEvent.type(screen.getByLabelText(/Quantity to receive/), '5')
    expect(screen.getByRole('button', { name: /confirm receipt/i })).toBeEnabled()
  })

  it('shows the low-quality message when the scan endpoint rejects the photo', async () => {
    stubFetchRoutes({
      ...routes,
      '/api/batch-intake/scan': [422, { detail: 'Image is too blurry' }],
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    const input = screen.getByTestId('package-file-input') as HTMLInputElement
    await userEvent.upload(input, packImage())
    await userEvent.click(screen.getByRole('button', { name: /scan package/i }))

    expect(await screen.findByText(/Unable to confidently read package information/i)).toBeInTheDocument()
    expect(screen.getByText(/Retake a flat, well-lit, close-up photo/i)).toBeInTheDocument()
  })
})