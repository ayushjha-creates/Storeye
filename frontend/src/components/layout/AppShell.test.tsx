import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../../edge/EdgeContext'
import { AuthProvider } from '../../auth/AuthContext'
import { AppShell } from './AppShell'
import { stubFetchRoutes } from '../../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

function me(overrides: Record<string, unknown> = {}) {
  return {
    id: 'aaaaaaaa-0000-4000-8000-000000000000',
    email: 'manager@storeye.local',
    name: 'Asha Store',
    role: 'MANAGER',
    store_id: STORE_ID,
    is_active: true,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    store_name: 'Asha Stores',
    demo_store: false,
    ...overrides,
  }
}

function routes(overrides: Record<string, unknown> = {}) {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/demo/status': { store_is_demo: false },
    '/api/auth/me': me(),
    ...overrides,
  }
}

function renderShell() {
  render(
    <AuthProvider>
      <EdgeProvider>
        <MemoryRouter initialEntries={['/']}>
          <AppShell />
        </MemoryRouter>
      </EdgeProvider>
    </AuthProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AppShell', () => {
  it('shows the shopkeeper nav: Home, Sales, Stock, Receive Stock, Alerts, Reports, Cameras, Settings', async () => {
    stubFetchRoutes(routes())
    renderShell()

    const mainNav = await screen.findByRole('navigation', { name: 'Main' })
    for (const label of ['Home', 'Sales', 'Stock', 'Receive Stock', 'Alerts', 'Reports']) {
      expect(within(mainNav).getByRole('link', { name: label })).toBeInTheDocument()
    }

    const opsNav = screen.getByRole('navigation', { name: 'Store operations' })
    expect(within(opsNav).getByRole('link', { name: 'Cameras' })).toBeInTheDocument()
    expect(within(opsNav).getByRole('link', { name: 'Settings' })).toBeInTheDocument()
  })

  it('never leaks advanced AI pages into the primary nav', async () => {
    stubFetchRoutes(routes())
    renderShell()

    await screen.findByRole('navigation', { name: 'Main' })
    expect(screen.queryByText(/product intelligence/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/shelf intelligence/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/ai observations/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/reconciliation/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/customer journeys/i)).not.toBeInTheDocument()
  })

  it('shows the Demo entry only when the store is the deterministic demo store', async () => {
    stubFetchRoutes(
      routes({
        '/api/demo/status': { store_is_demo: true },
        '/api/auth/me': me({ demo_store: true }),
      }),
    )
    renderShell()

    const opsNav = await screen.findByRole('navigation', { name: 'Store operations' })
    expect(within(opsNav).getByRole('link', { name: /demo/i })).toBeInTheDocument()
  })

  it('keeps a mobile bottom bar with the five main actions plus More → Settings', async () => {
    stubFetchRoutes(routes())
    renderShell()

    const bottom = await screen.findByRole('navigation', { name: 'Primary' })
    for (const label of ['Home', 'Sales', 'Stock', 'Receive', 'Alerts']) {
      expect(within(bottom).getByText(label)).toBeInTheDocument()
    }
    expect(within(bottom).getByText('More')).toBeInTheDocument()
    expect(within(bottom).getByRole('link', { name: /more/i })).toHaveAttribute('href', '/app/settings')
  })
})