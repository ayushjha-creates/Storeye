import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ProductIntelligencePage } from './ProductIntelligence'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000002'

const ROWS = [
  {
    ai_class: 'Lays',
    mapped: true,
    product_id: PRODUCT_ID,
    product_name: 'Lays Classic',
    sku: 'LAYS-1',
    camera_id: 'c1',
    camera_name: 'Shelf Cam',
    shelf_code: 'A1',
    visible_count: 2,
    confidence: 0.91,
    counting_rule: 'max_simultaneous_per_frame',
    latest_observed_at: '2026-09-07T08:00:00Z',
    database_quantity: 5,
    difference: -3,
    comparison_status: 'POSSIBLE_SHORTAGE',
    message: null,
  },
  {
    ai_class: 'CocaCola',
    mapped: false,
    product_id: null,
    product_name: null,
    sku: null,
    camera_id: 'c1',
    camera_name: 'Shelf Cam',
    shelf_code: 'A1',
    visible_count: 3,
    confidence: 0.8,
    counting_rule: 'max_simultaneous_per_frame',
    latest_observed_at: '2026-09-07T08:01:00Z',
    database_quantity: null,
    difference: null,
    comparison_status: 'NOT_ASSESSED',
    message: 'Unknown product — the model detected this class but it is not mapped to a catalog product. Map it via Product.ai_classes; nothing is guessed.',
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProductIntelligencePage', () => {
  it('renders visible vs recorded comparison including shortages and unmapped classes', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/products': { items: ROWS, total: 2 },
      '/api/products': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <ProductIntelligencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /product intelligence/i })).toBeInTheDocument()
    expect(screen.getByText('Lays Classic')).toBeInTheDocument()
    expect(screen.getByText('Possible shortage (fewer visible than recorded)')).toBeInTheDocument()
    expect(screen.getAllByText(/unknown product — map to catalog/i).length).toBeGreaterThan(0)
    expect(screen.getByText('CocaCola')).toBeInTheDocument()
    // DB inventory of the mapped product shown; unmapped shows no inventory.
    expect(screen.getAllByText('5').length).toBeGreaterThan(0)
  })

  it('maps an unmapped class to a product through the ai_classes PATCH', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/products': { items: ROWS, total: 2 },
      '/api/products': {
        items: [{ id: PRODUCT_ID, store_id: STORE_ID, sku: 'LAYS-1', name: 'Lays Classic', selling_price: '10.00', tax_rate: '0.05', is_active: true }],
        total: 1,
      },
    })
    render(
      <MemoryRouter>
        <ProductIntelligencePage />
      </MemoryRouter>,
    )

    const mapButton = await screen.findByRole('button', { name: /map to product/i })
    await userEvent.click(mapButton)

    expect(screen.getByRole('dialog', { name: /CocaCola.*to a product/i })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole('combobox'), PRODUCT_ID)
    await userEvent.click(screen.getByRole('button', { name: /map class/i }))

    expect(
      fetchMock.mock.calls.some(
        (c) => String(c[0]).includes('/api/products/') && String(c[0]).includes('PATCH') === false,
      ),
    ).toBe(true)
    const patch = fetchMock.mock.calls.find((c) => String(c[0]).includes(`/api/products/${PRODUCT_ID}`))
    expect(patch).toBeTruthy()
    const [, opts] = patch as [string, { method: string; body?: string }]
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(String(opts.body))).toMatchObject({ ai_classes: ['CocaCola'] })
  })

  it('shows a link to related open shortage/surplus alerts', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/products': { items: ROWS, total: 2 },
      '/api/products': { items: [], total: 0 },
      '/api/alerts': {
        items: [
          {
            id: '11111111-0000-4000-8000-000000000001',
            store_id: STORE_ID,
            camera_id: 'c1',
            product_id: PRODUCT_ID,
            shelf_id: null,
            alert_type: 'SHORTAGE',
            severity: 'CRITICAL',
            status: 'OPEN',
            title: 'Possible shortage: Lays Classic',
            message: 'AI sees 2 visible; inventory records 5.',
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
    render(
      <MemoryRouter>
        <ProductIntelligencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/1 related open alert/i)).toBeInTheDocument()
    expect(screen.getByText('View in Alerts →')).toBeInTheDocument()
    expect(screen.getByText(/possible shortage: lays classic/i)).toBeInTheDocument()
  })
})