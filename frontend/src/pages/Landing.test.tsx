import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { LandingPage } from './Landing'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderLanding() {
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

  it('shows the dashboard links when a session exists', () => {
    window.localStorage.setItem(
      'storeye.auth.session',
      JSON.stringify({ userName: 'Ravi', role: 'ASSOCIATE', loginAt: new Date().toISOString() }),
    )
    renderLanding()
    expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveAttribute('href', '/app')
    expect(screen.getByRole('link', { name: /start exploring/i })).toHaveAttribute('href', '/app')
  })
})