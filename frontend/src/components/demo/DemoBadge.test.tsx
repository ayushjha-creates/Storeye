import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { DemoBadge } from './DemoBadge'
import { stubFetchRoutes } from '../../test/mock'

const DEMO_STATUS = {
  demo_mode: true,
  demo_store: 'Storeye Demo Mart',
  demo_store_id: 'aaaabbbb-0000-4000-8000-000000000001',
  store_exists: true,
  store_is_demo: true,
  active_key: 'NORMAL_STORE',
  scenario: null,
  last_reset_at: null,
  last_activated_at: null,
}

const REAL_STATUS = {
  ...DEMO_STATUS,
  demo_mode: false,
  store_is_demo: false,
  active_key: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderBadge() {
  return render(
    <MemoryRouter>
      <DemoBadge />
    </MemoryRouter>,
  )
}

describe('DemoBadge', () => {
  it('labels a demo store explicitly', async () => {
    stubFetchRoutes({ '/api/demo/status': DEMO_STATUS })
    renderBadge()
    expect(await screen.findByText('Demo store')).toBeInTheDocument()
    expect(screen.queryByText('Real data')).not.toBeInTheDocument()
  })

  it('labels a real store as real data', async () => {
    stubFetchRoutes({ '/api/demo/status': REAL_STATUS })
    renderBadge()
    expect(await screen.findByText('Real data')).toBeInTheDocument()
    expect(screen.queryByText('Demo store')).not.toBeInTheDocument()
  })
})
