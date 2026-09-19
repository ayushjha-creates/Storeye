import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AlertsPage } from './Alerts'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const ALERT_CRITICAL = {
  id: '11111111-0000-4000-8000-000000000001',
  store_id: STORE_ID,
  camera_id: 'c1',
  product_id: 'p1',
  shelf_id: null,
  alert_type: 'SHORTAGE',
  severity: 'CRITICAL',
  status: 'OPEN',
  title: 'Possible shortage: Lays (LAYS-1)',
  message: 'AI sees 1 visible; inventory records 4. Informational — review before any adjustment.',
  confidence: 0.9,
  source_type: 'product_intelligence',
  source_id: null,
  first_detected_at: '2026-09-07T08:00:00Z',
  last_detected_at: '2026-09-07T08:05:00Z',
  acknowledged_at: null,
  resolved_at: null,
  dismissed_at: null,
  details: {
    source: 'product_intelligence',
    database_quantity: 4,
    ai_observed_quantity: 1,
    difference: -3,
    counting_rule: 'max_simultaneous_per_frame',
  },
  created_at: '2026-09-07T08:00:00Z',
  updated_at: '2026-09-07T08:05:00Z',
}

const ALERT_MISPLACEMENT = {
  id: '22222222-0000-4000-8000-000000000002',
  store_id: STORE_ID,
  camera_id: 'c1',
  product_id: 'p2',
  shelf_id: 's1',
  alert_type: 'MISPLACEMENT',
  severity: 'LOW',
  status: 'OPEN',
  title: 'Possible misplacement: Maggi on shelf A1',
  message: 'AI detected Maggi on a shelf whose planogram expects other products.',
  confidence: 0.87,
  source_type: 'shelf_intelligence',
  source_id: null,
  first_detected_at: '2026-09-07T08:00:00Z',
  last_detected_at: '2026-09-07T08:00:00Z',
  acknowledged_at: null,
  resolved_at: null,
  dismissed_at: null,
  details: { expected_product: 'Lays', detected_product: 'Maggi', shelf_code: 'A1' },
  created_at: '2026-09-07T08:00:00Z',
  updated_at: '2026-09-07T08:00:00Z',
}

function twoAlertRoutes() {
  return {
    '/api/alerts/evaluate': {
      evaluated_at: '2026-09-07T09:00:00Z',
      store_id: STORE_ID,
      hours: 24,
      generated: 1,
      updated: 0,
      skipped: 0,
      alerts: [ALERT_CRITICAL],
    },
    '/api/alerts': { items: [ALERT_CRITICAL, ALERT_MISPLACEMENT], total: 2 },
    '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AlertsPage', () => {
  it('renders the alert inbox with stats and alert actions', async () => {
    stubFetchRoutes(twoAlertRoutes())
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /things that need attention/i })).toBeInTheDocument()
    expect(screen.getByText(/possible shortage: lays/i)).toBeInTheDocument()
    expect(screen.getByText(/possible misplacement: maggi/i)).toBeInTheDocument()
    expect(screen.getAllByText('Urgent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('OPEN').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /check now/i })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /acknowledge/i }).length).toBeGreaterThan(0)
  })

  it('acknowledges an alert through the lifecycle endpoint', async () => {
    const fetchMock = stubFetchRoutes({
      ...twoAlertRoutes(),
      '/acknowledge': { ...ALERT_CRITICAL, status: 'ACKNOWLEDGED', acknowledged_at: '2026-09-07T09:30:00Z' },
    })
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    const acknowledgeButton = await screen.findAllByRole('button', { name: /acknowledge/i })
    await userEvent.click(acknowledgeButton[0])

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes(`${ALERT_CRITICAL.id}/acknowledge`)),
    ).toBe(true)
    expect(await screen.findByText('ACKNOWLEDGED')).toBeInTheDocument()
  })

  it('resolves and dismisses only from the allowed lifecycle', async () => {
    const fetchMock = stubFetchRoutes({
      ...twoAlertRoutes(),
      '/resolve': { ...ALERT_CRITICAL, status: 'RESOLVED', resolved_at: '2026-09-07T09:30:00Z' },
      '/dismiss': { ...ALERT_MISPLACEMENT, status: 'DISMISSED', dismissed_at: '2026-09-07T09:30:00Z' },
    })
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    const resolveButtons = await screen.findAllByRole('button', { name: /^resolve$/i })
    const dismissButtons = await screen.findAllByRole('button', { name: /^dismiss$/i })
    await userEvent.click(resolveButtons[0])
    await userEvent.click(dismissButtons[0])

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('resolve'))).toBe(true)
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('dismiss'))).toBe(true)
    expect(await screen.findByText('RESOLVED')).toBeInTheDocument()
    expect(await screen.findByText('DISMISSED')).toBeInTheDocument()
  })

  it('opens the evidence panel with persisted details', async () => {
    stubFetchRoutes(twoAlertRoutes())
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    const evidenceButtons = await screen.findAllByRole('button', { name: /evidence/i })
    await userEvent.click(evidenceButtons[0])

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/database_quantity/i)).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText(/max_simultaneous_per_frame/i)).toBeInTheDocument()
    expect(screen.getByText(/informational\/actionable/i)).toBeInTheDocument()
  })

  it('filters by status via query params', async () => {
    const fetchMock = stubFetchRoutes({
      ...twoAlertRoutes(),
      'status=RESOLVED': { items: [{ ...ALERT_CRITICAL, status: 'RESOLVED', resolved_at: '2026-09-07T10:00:00Z' }], total: 1 },
    })
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

await screen.findByRole('heading', { name: /things that need attention/i })
    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), 'RESOLVED')

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('status=RESOLVED')),
    ).toBe(true)
    expect(await screen.findByText('RESOLVED')).toBeInTheDocument()
  })

  it('runs the evaluate endpoint and refreshes the list', async () => {
    const fetchMock = stubFetchRoutes(twoAlertRoutes())
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /check now/i }))

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/alerts/evaluate')),
    ).toBe(true)
    expect(await screen.findByRole('heading', { name: /things that need attention/i })).toBeInTheDocument()
  })
})