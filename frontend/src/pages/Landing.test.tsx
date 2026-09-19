import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { LandingPage } from './Landing'
import { stubFetchRoutes } from '../test/mock'

const USER = {
  id: 'u1',
  email: 'ravi@storeye.local',
  name: 'Ravi',
  role: 'STAFF',
  store_id: 's1',
  is_active: true,
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  store_name: 'Test Store',
  demo_store: false,
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderLanding(authenticated = false) {
  stubFetchRoutes({
    '/api/auth/me': authenticated ? USER : [401, { detail: 'Not authenticated' }],
  })
  return render(
    <AuthProvider>
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    </AuthProvider>,
  )
}

describe('LandingPage', () => {
  it('renders the first-page image and core sections', () => {
    renderLanding()
    expect(
      screen.getByRole('img', { name: /storeye running on a laptop and smartphone/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /one dashboard for everything your store does/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /see it for yourself/i })).toHaveAttribute('href', '/login')
  })

  it('does not leak the word "demo" into the visible copy', () => {
    renderLanding()
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument()
  })

  it('shows the dashboard links when a session exists', async () => {
    renderLanding(true)
    expect(await screen.findByRole('link', { name: /open dashboard/i })).toHaveAttribute('href', '/app')
    expect(screen.getByRole('link', { name: /start exploring/i })).toHaveAttribute('href', '/app')
  })
})