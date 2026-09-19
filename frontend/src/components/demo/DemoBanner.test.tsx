import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { DemoBanner } from './DemoBanner'
import { stubFetchRoutes } from '../../test/mock'

const STATUS = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  demo_store_id: 'aaaabbbb-0000-4000-8000-000000000001',
  store_exists: true,
  store_is_demo: true,
  active_key: 'NORMAL_STORE',
  scenario: {
    key: 'NORMAL_STORE',
    name: 'Normal Store',
    description: 'Healthy baseline.',
    category: 'healthy',
  },
  last_reset_at: null,
  last_activated_at: null,
}

beforeEach(() => {
  window.localStorage.setItem('storeye.demo.presentation', '1')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('DemoBanner', () => {
  it('only resets the demo store after the user confirms', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/demo/reset': { ok: true },
      '/api/demo/status': STATUS,
    })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(
      <MemoryRouter>
        <DemoBanner />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /reset/i }))
    expect(confirmSpy).toHaveBeenCalled()
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/demo/reset'))).toBe(true)
  })

  it('does not reset when the confirmation is declined', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/demo/reset': { ok: true },
      '/api/demo/status': STATUS,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(
      <MemoryRouter>
        <DemoBanner />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /reset/i }))
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/demo/reset'))).toBe(false)
  })
})
