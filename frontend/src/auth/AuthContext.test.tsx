import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const USER = {
  id: 'u1',
  email: 'ravi@storeye.local',
  name: 'Ravi Kumar',
  role: 'MANAGER',
  store_id: 's1',
  is_active: true,
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  store_name: 'Test Store',
  demo_store: false,
}

function Probe() {
  const { isAuthenticated, isLoading, session, login, logout } = useAuth()
  return (
    <div>
      <span data-testid="loading">{isLoading ? 'loading' : 'ready'}</span>
      <span data-testid="auth-state">{isAuthenticated ? 'in' : 'out'}</span>
      <span data-testid="session-name">{session?.userName ?? 'none'}</span>
      <span data-testid="session-email">{session?.email ?? 'none'}</span>
      <button
        onClick={async () => {
          try {
            await login('ravi@storeye.local', 'secret')
          } catch {
            // expected when credentials are rejected / backend unreachable
          }
        }}
      >
        sign-in
      </button>
      <button onClick={() => logout()}>sign-out</button>
    </div>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('AuthContext', () => {
  it('signs in through the real backend and reflects the returned user', async () => {
    stubFetchRoutes({
      '/api/auth/me': [401, { detail: 'Not authenticated' }],
      '/api/auth/login': { user: USER, expires_in_seconds: 43200 },
    })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'))
    expect(screen.getByTestId('auth-state')).toHaveTextContent('out')

    await userEvent.click(screen.getByRole('button', { name: 'sign-in' }))

    expect(await screen.findByTestId('auth-state')).toHaveTextContent('in')
    expect(screen.getByTestId('session-name')).toHaveTextContent('Ravi Kumar')
    expect(screen.getByTestId('session-email')).toHaveTextContent('ravi@storeye.local')
  })

  it('restores an existing session from the cookie via GET /api/auth/me', async () => {
    stubFetchRoutes({ '/api/auth/me': USER })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(await screen.findByTestId('auth-state')).toHaveTextContent('in')
    expect(screen.getByTestId('session-name')).toHaveTextContent('Ravi Kumar')
  })

  it('stays signed out when there is no valid session', async () => {
    stubFetchRoutes({ '/api/auth/me': [401, { detail: 'Not authenticated' }] })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'))
    expect(screen.getByTestId('auth-state')).toHaveTextContent('out')
  })

  it('stays signed out when the backend is unreachable', async () => {
    stubFetchReject()
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'))
    expect(screen.getByTestId('auth-state')).toHaveTextContent('out')
  })

  it('signs out and clears the session', async () => {
    stubFetchRoutes({
      '/api/auth/me': USER,
      '/api/auth/logout': { message: 'Signed out' },
    })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(await screen.findByTestId('auth-state')).toHaveTextContent('in')

    await userEvent.click(screen.getByRole('button', { name: 'sign-out' }))
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('out'))
    expect(screen.getByTestId('session-name')).toHaveTextContent('none')
  })
})
