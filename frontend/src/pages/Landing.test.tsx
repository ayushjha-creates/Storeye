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
  it('renders the hero and public CTAs', () => {
    renderLanding()
    expect(screen.getByRole('heading', { name: /run your store/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /sign in to storeye/i })).toBeInTheDocument()
    expect(screen.getByText(/edge-first · offline-first · private by design/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /see it for yourself/i })).toHaveAttribute('href', '/login')
  })

  it('does not leak the word "demo" into the visible copy', () => {
    renderLanding()
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument()
  })

  it('shows the dashboard CTA when a session exists', () => {
    window.localStorage.setItem(
      'storeye.auth.session',
      JSON.stringify({ userName: 'Ravi', role: 'ASSOCIATE', loginAt: new Date().toISOString() }),
    )
    renderLanding()
    expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveAttribute('href', '/app')
    expect(screen.queryByRole('link', { name: /sign in to storeye/i })).not.toBeInTheDocument()
  })
})