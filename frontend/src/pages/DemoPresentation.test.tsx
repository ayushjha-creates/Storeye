import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { DemoPresentationPage } from './DemoPresentation'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const NORMAL = {
  key: 'NORMAL_STORE',
  name: 'Normal Store',
  description: 'Healthy baseline: everything above reorder level.',
  category: 'healthy',
  expected: ['Store health HEALTHY'],
  focus_path: '/app/dashboard',
  active: true,
}

const LOW_SHELF = {
  key: 'LOW_SHELF_BACKSTOCK',
  name: 'Low Shelf + Back Stock',
  description: 'Inventory is available but the shelf looks empty.',
  category: 'shelf',
  expected: ['LOW_SHELF_AVAILABILITY insight', 'Replenish from back-stock'],
  focus_path: '/app/insights',
  active: true,
}

const STATUS = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  demo_store_id: STORE_ID,
  store_exists: true,
  store_is_demo: true,
  active_key: 'LOW_SHELF_BACKSTOCK',
  scenario: {
    key: 'LOW_SHELF_BACKSTOCK',
    name: 'Low Shelf + Back Stock',
    description: 'Inventory is available but the shelf looks empty.',
    category: 'shelf',
  },
  last_reset_at: '2026-09-17T09:00:00Z',
  last_activated_at: '2026-09-17T09:05:00Z',
}

const LIST = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  store_exists: true,
  store_is_demo: true,
  active_key: 'LOW_SHELF_BACKSTOCK',
  scenarios: [NORMAL, LOW_SHELF],
}

function routes() {
  return {
    '/api/demo/status': STATUS,
    '/api/demo/scenarios': LIST,
  }
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('DemoPresentationPage', () => {
  it('shows the active scenario and what is happening', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoPresentationPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /presentation/i })).toBeInTheDocument()
    expect(screen.getByText(/low shelf \+ back stock/i)).toBeInTheDocument()
    expect(screen.getByText(/low_shelf_availability insight/i)).toBeInTheDocument()
  })

  it('deep-links to the real application pages', async () => {
    stubFetchRoutes(routes())
    render(
      <MemoryRouter>
        <DemoPresentationPage />
      </MemoryRouter>,
    )

    const dashboard = await screen.findByRole('link', { name: /open dashboard/i })
    expect(dashboard).toHaveAttribute('href', '/app')
    expect(screen.getByRole('link', { name: /open insights/i })).toHaveAttribute('href', '/app/insights')
    expect(screen.getByRole('link', { name: /open smart receiving/i })).toHaveAttribute(
      'href',
      '/app/inventory/receive',
    )
  })

  it('degrades to a retryable error when the backend is unreachable', async () => {
    stubFetchReject()
    render(
      <MemoryRouter>
        <DemoPresentationPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
