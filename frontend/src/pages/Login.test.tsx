import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './Login'
import { stubFetchRoutes } from '../test/mock'

const USER = {
  id: 'u1',
  email: 'ravi@storeye.local',
  name: 'Ravi',
  role: 'OWNER',
  store_id: 's1',
  is_active: true,
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  store_name: 'Test Store',
  demo_store: false,
}

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
  it('renders the credential form', () => {
    stubFetchRoutes({ '/api/auth/me': [401, { detail: 'Not authenticated' }] })
    renderLogin()
    expect(screen.getByRole('heading', { name: /storeye/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in to storeye/i })).toBeInTheDocument()
  })

  it('signs in and navigates back to the originally requested page', async () => {
    stubFetchRoutes({
      '/api/auth/me': [401, { detail: 'Not authenticated' }],
      '/api/auth/login': { user: USER, expires_in_seconds: 43200 },
    })
    renderLogin()

    await userEvent.type(screen.getByLabelText('Email'), 'ravi@storeye.local')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse')

    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByTestId('cameras-route')).toBeInTheDocument()
  })

  it('shows the backend error for invalid credentials', async () => {
    stubFetchRoutes({
      '/api/auth/me': [401, { detail: 'Not authenticated' }],
      '/api/auth/login': [401, { detail: 'Invalid email or password' }],
    })
    renderLogin()

    await userEvent.type(screen.getByLabelText('Email'), 'ravi@storeye.local')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument()
    expect(screen.queryByTestId('cameras-route')).not.toBeInTheDocument()
  })

  it('maps a missing auth endpoint (404) to a clear message', async () => {
    stubFetchRoutes({
      '/api/auth/me': [401, { detail: 'Not authenticated' }],
      '/api/auth/login': [404, { detail: 'Not Found' }],
    })
    renderLogin()

    await userEvent.type(screen.getByLabelText('Email'), 'ravi@storeye.local')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse')
    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByText(/authentication service endpoint not found/i)).toBeInTheDocument()
    expect(screen.queryByText(/not found: not found/i)).not.toBeInTheDocument()
  })

  it('shows an edge-hub-unreachable error when the backend is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderLogin()

    await userEvent.type(screen.getByLabelText('Email'), 'ravi@storeye.local')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: /sign in to storeye/i }))

    expect(await screen.findByText(/cannot reach the local storeye edge hub/i)).toBeInTheDocument()
  })
})
