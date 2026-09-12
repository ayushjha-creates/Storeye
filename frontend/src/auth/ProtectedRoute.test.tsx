import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { AuthProvider } from './AuthContext'
import { ProtectedRoute, PublicOnlyRoute } from './ProtectedRoute'
import { stubFetchRoutes } from '../test/mock'

function ProtectedStub() {
  return <div data-testid="protected-content">PROTECTED AREA</div>
}

function LoginStub() {
  return <div data-testid="login-content">LOGIN PAGE</div>
}

function HomeStub() {
  return <div data-testid="home-content">HOME</div>
}

function renderWithAuth(initial: string[], session: unknown) {
  window.localStorage.clear()
  if (session) {
    window.localStorage.setItem('storeye.auth.session', JSON.stringify(session))
  }
  stubFetchRoutes({ '/api/health': { status: 'ok' } })
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={initial}>
        <Routes>
          <Route path="/" element={<HomeStub />} />
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <LoginStub />
              </PublicOnlyRoute>
            }
          />
          <Route
            path="/protected"
            element={
              <ProtectedRoute>
                <ProtectedStub />
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('route guards', () => {
  it('redirects an anonymous visitor away from a protected route to /login', async () => {
    renderWithAuth(['/protected'], null)
    expect(await screen.findByTestId('login-content')).toBeInTheDocument()
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
  })

  it('renders the protected area when a session exists', async () => {
    renderWithAuth(['/protected'], {
      userName: 'Ravi',
      role: 'ASSOCIATE',
      loginAt: new Date().toISOString(),
    })
    expect(await screen.findByTestId('protected-content')).toBeInTheDocument()
    expect(screen.queryByTestId('login-content')).not.toBeInTheDocument()
  })

  it('sends an authenticated user away from /login to the dashboard', async () => {
    renderWithAuth(['/login'], {
      userName: 'Ravi',
      role: 'ASSOCIATE',
      loginAt: new Date().toISOString(),
    })
    expect(await screen.findByTestId('home-content')).toBeInTheDocument()
  })
})