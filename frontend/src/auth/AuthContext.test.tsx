import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

function Probe() {
  const { isAuthenticated, session, login, logout } = useAuth()
  return (
    <div>
      <span data-testid="auth-state">{isAuthenticated ? 'in' : 'out'}</span>
      <span data-testid="session-name">{session?.userName ?? 'none'}</span>
      <button
        onClick={async () => {
          try {
            await login('Ravi Kumar', 'anything')
          } catch {
            // expected when the edge hub is unreachable
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
  it('records a local session once the Edge Hub is reachable', async () => {
    stubFetchRoutes({ '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' } })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('auth-state')).toHaveTextContent('out')

    await userEvent.click(screen.getByRole('button', { name: 'sign-in' }))

    expect(await screen.findByTestId('auth-state')).toHaveTextContent('in')
    expect(screen.getByTestId('session-name')).toHaveTextContent('Ravi Kumar')
  })

  it('stays signed out when the local Edge Hub is unreachable', async () => {
    stubFetchReject()
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'sign-in' }))
    expect(await screen.findByTestId('auth-state')).toHaveTextContent('out')
  })

  it('signs out and clears the local session', async () => {
    stubFetchRoutes({ '/api/health': { status: 'ok' } })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'sign-in' }))
    expect(await screen.findByTestId('auth-state')).toHaveTextContent('in')

    await userEvent.click(screen.getByRole('button', { name: 'sign-out' }))
    expect(screen.getByTestId('auth-state')).toHaveTextContent('out')
    expect(screen.getByTestId('session-name')).toHaveTextContent('none')
  })
})