import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { DemoControlCenterPage } from './DemoControlCenter'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const NORMAL = {
  key: 'NORMAL_STORE',
  name: 'Normal Store',
  description: 'Healthy baseline: everything above reorder level.',
  category: 'healthy',
  expected: ['Store health HEALTHY', 'No HIGH/MEDIUM insights'],
  focus_path: '/app/dashboard',
  active: true,
}

const LOW_STOCK = {
  key: 'LOW_STOCK',
  name: 'Low Stock',
  description: 'A fast-moving product falls to its reorder level.',
  category: 'inventory',
  expected: ['LOW_STOCK insight (MEDIUM)', 'Store health ATTENTION'],
  focus_path: '/app/insights',
  active: false,
}

const SCENARIO_LIST = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  store_exists: true,
  store_is_demo: true,
  active_key: 'NORMAL_STORE',
  scenarios: [NORMAL, LOW_STOCK],
}

const STATUS = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  demo_store_id: STORE_ID,
  store_exists: true,
  store_is_demo: true,
  active_key: 'NORMAL_STORE',
  scenario: {
    key: 'NORMAL_STORE',
    name: 'Normal Store',
    description: 'Healthy baseline: everything above reorder level.',
    category: 'healthy',
  },
  last_reset_at: null,
  last_activated_at: '2026-09-17T09:00:00Z',
}

const ACTIVATION = {
  ok: true,
  active_key: 'LOW_STOCK',
  scenario: LOW_STOCK,
  store: { id: STORE_ID, name: 'Storeye Demo Mart' },
  metrics: { low_stock_product: 'MAGGI-2MIN' },
  evaluation: {
    candidates: 4,
    created: 4,
    refreshed: 0,
    resolved: 0,
    expired: 0,
    alerts_created: 1,
    alerts_updated: 0,
  },
  activated_at: '2026-09-17T09:05:00Z',
}

function routes(overrides: Record<string, unknown> = {}) {
  return {
    '/api/demo/scenarios/LOW_STOCK/activate': ACTIVATION,
    '/api/demo/reset': { ...ACTIVATION, active_key: 'NORMAL_STORE', scenario: NORMAL },
    '/api/demo/status': STATUS,
    '/api/demo/scenarios': SCENARIO_LIST,
    ...overrides,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  // Destructive demo actions are confirmation-gated; accept by default.
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('DemoControlCenterPage', () => {
  it('renders the active scenario and the deterministic scenario catalog', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    expect(
      await screen.findByRole('heading', { name: /demo control center/i }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('active-scenario')).toHaveTextContent(/normal store/i)
    expect(screen.getByText(/low stock/i)).toBeInTheDocument()
    expect(screen.getByText(/store health attention/i)).toBeInTheDocument()
    expect(screen.getByText(/2 deterministic scenarios/i)).toBeInTheDocument()
    // Active scenario cannot be re-activated.
    expect(screen.getByRole('button', { name: /activate normal store/i })).toBeDisabled()
  })

  it('activates a scenario through the guarded backend endpoint', async () => {
    const fetchMock = stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /activate low stock/i }))

    const call = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes('/api/demo/scenarios/LOW_STOCK/activate'),
    )
    expect(call).toBeTruthy()
    const options = call?.[1] as { headers?: Record<string, string> } | undefined
    expect(options?.headers?.['X-Demo-Reset-Key']).toBe('storeye-demo-reset')
    expect(await screen.findByRole('status')).toHaveTextContent(/activated/i)
  })

  it('resets to the normal baseline', async () => {
    const fetchMock = stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /reset to normal/i }))

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/demo/reset')),
    ).toBe(true)
  })

  it('does not reset or activate when the confirmation is declined', async () => {
    const fetchMock = stubFetchRoutes(routes())
    vi.mocked(window.confirm).mockReturnValue(false)
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /activate low stock/i }))
    await userEvent.click(screen.getByRole('button', { name: /reset to normal/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/activate'))).toBe(false)
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/demo/reset'))).toBe(false)
  })

  it('toggles presentation mode and persists the preference', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    const toggle = await screen.findByRole('button', { name: /presentation mode/i })
    await userEvent.click(toggle)

    expect(window.localStorage.getItem('storeye.demo.presentation')).toBe('1')
    expect(
      await screen.findByRole('button', { name: /exit presentation/i }),
    ).toBeInTheDocument()
  })

  it('shows a retryable error when the backend is down', async () => {
    stubFetchReject()
    render(
      <MemoryRouter>
        <DemoControlCenterPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
