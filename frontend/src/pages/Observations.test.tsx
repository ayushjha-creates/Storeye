import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { ObservationsPage } from './Observations'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const CAMERA_ID = 'aaaabbbb-0000-4000-8000-000000000002'

const OBS = [
  {
    id: 'o1',
    observation_type: 'PERSON',
    store_id: STORE_ID,
    camera_id: CAMERA_ID,
    product_id: null,
    batch_id: null,
    track_id: 1,
    frame_number: 100,
    source: 'stream-1',
    confidence: 0.9,
    bbox: [10, 10, 20, 20],
    text: null,
    observed_at: '2026-09-06T10:00:00Z',
  },
  {
    id: 'o2',
    observation_type: 'PRODUCT',
    store_id: STORE_ID,
    camera_id: CAMERA_ID,
    product_id: null,
    batch_id: null,
    track_id: null,
    frame_number: 102,
    source: 'stream-1',
    confidence: 0.76,
    bbox: [30, 10, 20, 20],
    text: 'Biscuit 1',
    observed_at: '2026-09-06T10:01:00Z',
  },
  {
    id: 'o3',
    observation_type: 'EXPIRY_METADATA',
    store_id: STORE_ID,
    camera_id: CAMERA_ID,
    product_id: null,
    batch_id: null,
    track_id: null,
    frame_number: 104,
    source: 'stream-1',
    confidence: 0.85,
    bbox: [40, 10, 20, 20],
    text: '10/2026',
    observed_at: '2026-09-06T10:02:00Z',
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ObservationsPage', () => {
  it('renders live observation counts and the timeline rows', async () => {
    stubFetchRoutes({
      '/api/observations': { items: OBS, total: 3 },
      '/api/cameras': {
        items: [
          { id: CAMERA_ID, store_id: STORE_ID, name: 'Front Counter', camera_type: 'usb', is_active: true, config: {} },
        ],
        total: 1,
      },
    })
    render(
      <MemoryRouter>
        <ObservationsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /ai observations/i })).toBeInTheDocument()
    expect(screen.getAllByText('PERSON').length).toBeGreaterThan(0)
    expect(screen.getAllByText('PRODUCT').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EXPIRY_METADATA').length).toBeGreaterThan(0)
    expect(screen.getByText('Biscuit 1')).toBeInTheDocument()
  })

  it('shows an empty timeline when there are no detections', async () => {
    stubFetchRoutes({
      '/api/observations': { items: [], total: 0 },
      '/api/cameras': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <ObservationsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/no observations match/i)).toBeInTheDocument()
  })

  it('paginates with a server-side offset while keeping the true total', async () => {
    const sample = Array.from({ length: 50 }, (_, i) => ({
      id: `o${i}`,
      observation_type: 'PERSON' as const,
      store_id: STORE_ID,
      camera_id: CAMERA_ID,
      product_id: null,
      batch_id: null,
      track_id: i,
      frame_number: null,
      source: null,
      confidence: 0.8,
      bbox: null,
      text: null,
      observed_at: '2026-09-06T10:00:00Z',
    }))
    const fetchMock = stubFetchRoutes({
      '/api/observations': { items: sample, total: 120 },
      '/api/cameras': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <ObservationsPage />
      </MemoryRouter>,
    )

    expect(
      await screen.findByText(/120 observation\(s\) · page 1 of 3/i),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    await screen.findByText(/120 observation\(s\) · page 2 of 3/i)
    expect(fetchMock.mock.calls.some(([url]) =>
      String(url).includes('/api/observations') && String(url).includes('offset=50'),
    )).toBe(true)
  })

  it('sends server-side camera + confidence filters to the backend', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/observations': { items: [OBS[0]], total: 1 },
      '/api/cameras': {
        items: [
          { id: CAMERA_ID, store_id: STORE_ID, name: 'Front Counter', camera_type: 'usb', is_active: true, config: {} },
        ],
        total: 1,
      },
    })
    render(
      <MemoryRouter>
        <ObservationsPage />
      </MemoryRouter>,
    )

    const cameraSelect = await screen.findByRole('combobox', { name: /camera/i })
    await userEvent.selectOptions(cameraSelect, CAMERA_ID)
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) =>
        String(url).includes(`camera_id=${CAMERA_ID}`),
      )).toBe(true)
    })
  })
})