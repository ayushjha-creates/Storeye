import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './Login'
import { stubFetchRoutes } from '../test/mock'

function renderLogin() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/login?from=%2Fcameras']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/cameras" element={<div data-testid="cameras-route">CAMERAS</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('LoginPage', () => {
  it('renders the sign-in form with the auth-limitation note', () => {
    renderLogin()
    expect(screen.getByRole('heading', { name: /storeye/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('PIN / Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in to storeye/i })).toBeInTheDocument()
    expect(screen.getByText(/does not provide backend security/i)).toBeInTheDocument()
  })

  it('signs in and navigates back to the originally requested page', async () => {
    stubFetchRoutes({ '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' } })
    renderLogin()

    await userEvent.type(screen.getByLabelText('Name'), 'Ravi')
    await userEvent.type(screen.getByLabelText('PIN / Password'), 'anything-goes-today')

    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByTestId('cameras-route')).toBeInTheDocument()
    expect(window.localStorage.getItem('storeye.auth.session')).toContain('Ravi')
  })

  it('shows an edge-hub-unreachable error when the backend is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderLogin()

    await userEvent.type(screen.getByLabelText('Name'), 'Ravi')
    await userEvent.type(screen.getByLabelText('PIN / Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByText(/cannot reach the local storeye edge hub/i)).toBeInTheDocument()
  })
})