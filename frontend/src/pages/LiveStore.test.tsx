import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../edge/EdgeContext'
import { AuthProvider } from '../auth/AuthContext'
import { LiveStorePage } from './LiveStore'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

function liveRoutes() {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/stores': {
      items: [{ id: STORE_ID, name: 'Storeye Demo Mart', city: 'New Delhi' }],
      total: 1,
    },
    '/api/cameras': {
      items: [
        {
          id: 'aaaabbbb-0000-4000-8000-000000000003',
          store_id: STORE_ID,
          name: 'Demo Shelf Camera',
          location: 'Reckoning wall',
          camera_type: 'usb',
          is_active: true,
          config: {},
        },
      ],
      total: 1,
    },
    '/api/zones': {
      items: [{ id: 'aaaabbbb-0000-4000-8000-000000000004', store_id: STORE_ID, name: 'Snacks', description: null }],
      total: 1,
    },
    '/api/shelves': {
      items: [
        {
          id: 'aaaabbbb-0000-4000-8000-000000000005',
          store_id: STORE_ID,
          zone_id: 'aaaabbbb-0000-4000-8000-000000000004',
          code: 'A1',
          description: null,
        },
      ],
      total: 1,
    },
    '/api/observations': {
      items: [
        {
          id: '11111111-0000-4000-8000-000000000001',
          observation_type: 'PERSON',
          store_id: STORE_ID,
          camera_id: null,
          product_id: null,
          batch_id: null,
          track_id: 1,
          frame_number: 10,
          source: 'demo',
          confidence: 0.9,
          bbox: [10, 10, 20, 20],
          text: 'person (track 1)',
          source_observation_id: null,
          observed_at: new Date().toISOString(),
          details: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    },
    '/api/intelligence/shelves': { items: [], total: 0 },
    '/api/intelligence/products': { items: [], total: 0 },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('LiveStorePage', () => {
  it('renders live KPIs and the registered store from real APIs', async () => {
    stubFetchRoutes(liveRoutes())
    render(
      <AuthProvider>
        <EdgeProvider>
          <MemoryRouter>
            <LiveStorePage />
          </MemoryRouter>
        </EdgeProvider>
      </AuthProvider>,
    )

    expect(await screen.findByRole('heading', { name: /live store/i })).toBeInTheDocument()
    expect(screen.getByText(/storeye mart/i)).toBeInTheDocument()
    expect(screen.getByText('People in store')).toBeInTheDocument()
    expect(screen.getAllByText('Active cameras').length).toBeGreaterThan(0)
    expect(screen.getByText('Shelf Camera')).toBeInTheDocument()
  })

  it('shows the empty state when no shelving is configured', async () => {
    stubFetchRoutes({ ...liveRoutes(), '/api/shelves': { items: [], total: 0 } })
    render(
      <AuthProvider>
        <EdgeProvider>
          <MemoryRouter>
            <LiveStorePage />
          </MemoryRouter>
        </EdgeProvider>
      </AuthProvider>,
    )

    expect(await screen.findByText(/no shelving configured/i)).toBeInTheDocument()
  })
})