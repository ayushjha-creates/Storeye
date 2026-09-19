import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
  '/api/mobile-intake/status': {
    monitoring: true,
    watcher_alive: true,
    intake_dir: '/tmp/storeye/intake',
    processing_dir: '/tmp/storeye/processing',
    processed_dir: '/tmp/storeye/processed',
    failed_dir: '/tmp/storeye/failed',
    watched_at: '2026-09-17T08:00:00Z',
    started_at: '2026-09-17T07:00:00Z',
    scans: 2,
    duplicates: 1,
    rejected: 0,
    active_jobs: 1,
    failed_jobs: 0,
  },
  '/api/mobile-intake/jobs': { items: [], count: 0 },
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

    await screen.findByText('Receive Stock')

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

  it('loads a watcher-received USB job into the review form without re-scanning', async () => {
    const JOB_ID = 'job-00000000-0000-4000-8000-000000000009'
    stubFetchRoutes({
      ...routes,
      '/api/mobile-intake/jobs': {
        count: 1,
        items: [
          {
            job_id: JOB_ID,
            filename: 'storeye-aashirvaad.jpg',
            size: 178990,
            state: 'REVIEW_REQUIRED',
            demo: true,
            duplicate_of: null,
            error: null,
            note: null,
            acceptable: true,
            reason: 'Barcode matched Aashirvaad Atta 5kg.',
            candidate: {
              barcode_read: true,
              barcode: '8901063001015',
              product_id: PRODUCT_ID,
              product_name: 'Aashirvaad Atta 5kg',
              product_sku: 'AAS-ATTA',
              product_found: true,
              batch_number: 'M25-DEMO-01',
              manufacturing_date: '2026-08-01',
              expiry_date: '2027-08-01',
              expiry_date_precision: 'month',
              mrp: '240.00',
              confidence: 0.8,
              labels_found: ['exp', 'mfg', 'batch', 'mrp'],
              warnings: [],
            },
            created_at: '2026-09-17T08:01:00Z',
            updated_at: '2026-09-17T08:01:05Z',
          },
        ],
      },
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Scan with your phone')).toBeInTheDocument()
    expect(await screen.findByText(/Listening in \/tmp\/storeye\/intake/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /review candidate/i }))

    // The watcher's candidate prefills the same M17 review form.
    expect(await screen.findByText(/Barcode matched Aashirvaad Atta 5kg/i)).toBeInTheDocument()
    expect(productSelect()).toHaveValue(PRODUCT_ID)
    expect(screen.getByLabelText('Batch number')).toHaveValue('M25-DEMO-01')
    expect(screen.getByLabelText('Expiry date')).toHaveValue('2027-08-01')
    // Quantity is never guessed — the human must enter it.
    expect(screen.getByRole('button', { name: /confirm receipt/i })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Quantity to receive/), '20')
    expect(screen.getByRole('button', { name: /confirm receipt/i })).toBeEnabled()
  })

  it('offers rescan for a FAILED USB job and posts to the rescan endpoint', async () => {
    const fetchMock = stubFetchRoutes({
      ...routes,
      '/api/mobile-intake/jobs': {
        count: 1,
        items: [
          {
            job_id: 'job-failed',
            filename: 'blurry-biscuit.jpg',
            size: 1024,
            state: 'FAILED',
            demo: false,
            duplicate_of: null,
            error: '[SCAN_FAILED] no candidate',
            note: null,
            acceptable: null,
            reason: null,
            candidate: null,
            photo_url: null,
            created_at: '2026-09-17T08:01:00Z',
            updated_at: '2026-09-17T08:01:05Z',
          },
        ],
      },
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    await userEvent.click(
      await screen.findByRole('button', { name: /rescan blurry-biscuit\.jpg/i }),
    )
    await waitFor(() => {
      const rescanPosts = fetchMock.mock.calls.filter((c) =>
        String(c[0]).includes('/api/mobile-intake/jobs/job-failed/rescan'),
      )
      expect(rescanPosts.length).toBeGreaterThan(0)
    })
  })

  it('closes the USB job after a confirmed receipt', async () => {
    const fetchMock = stubFetchRoutes({
      ...routes,
      '/api/mobile-intake/jobs': {
        count: 1,
        items: [
          {
            job_id: 'job-open',
            filename: 'usb-photo.jpg',
            size: 2048,
            state: 'REVIEW_REQUIRED',
            demo: false,
            duplicate_of: null,
            error: null,
            note: null,
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
            photo_url: null,
            created_at: '2026-09-17T08:01:00Z',
            updated_at: '2026-09-17T08:01:05Z',
          },
        ],
      },
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /review candidate/i }))
    await screen.findByText(/Barcode matched Amul Milk 1L/i)
    await userEvent.type(screen.getByLabelText(/Quantity to receive/), '3')
    await userEvent.click(screen.getByRole('button', { name: /confirm receipt/i }))

    expect(await screen.findByText('Stock received')).toBeInTheDocument()
    await waitFor(() => {
      const closePosts = fetchMock.mock.calls.filter((c) =>
        String(c[0]).includes('/api/mobile-intake/jobs/job-open/close'),
      )
      expect(closePosts.length).toBeGreaterThan(0)
    })
  })

  it('queues a demo package with the reset key and shows the confirmation note', async () => {
    const fetchMock = stubFetchRoutes({
      ...routes,
      '/api/mobile-intake/demo-queue': {
        queued: true,
        filename: 'storeye-demo-8901063001015.jpg',
        size: 178990,
        sha256: 'ca8a227ba65b',
        demo: true,
        note: 'Queued for the intake watcher.',
      },
    })
    render(
      <MemoryRouter>
        <ReceiveSmartPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /queue demo package/i }))

    expect(await screen.findByText(/queued — the watcher will decode it in a moment/i)).toBeInTheDocument()
    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes('/api/mobile-intake/demo-queue'),
    )
    expect(posts).toHaveLength(1)
    const headers = posts[0][1]?.headers as Record<string, string>
    expect(headers['X-Demo-Reset-Key']).toBe('storeye-demo-reset')
  })
})