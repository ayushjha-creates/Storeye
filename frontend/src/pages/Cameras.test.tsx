import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import { CamerasPage } from './Cameras'
import { stubFetchRoutes, stubFetchReject } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const CAM = {
  id: 'c1',
  store_id: STORE_ID,
  name: 'Front Counter',
  location: 'Entrance',
  camera_type: 'usb',
  is_active: true,
  config: {},
}

const CAM2 = {
  id: 'c2',
  store_id: STORE_ID,
  name: 'Aisle 4',
  location: 'Dairy section',
  camera_type: 'rtsp',
  is_active: false,
  config: {},
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CamerasPage', () => {
  it('renders each camera with its status and latest observation', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM, CAM2], total: 2 },
      '/api/observations': {
        items: [
          {
            id: 'o1',
            observation_type: 'PRODUCT',
            store_id: STORE_ID,
            camera_id: 'c1',
            product_id: null,
            track_id: null,
            confidence: 0.87,
            bbox: [10, 20, 30, 40],
            text: 'Amul Milk 1L',
            observed_at: '2026-09-06T10:00:00Z',
          },
        ],
        total: 1,
      },
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Front Counter')).toBeInTheDocument()
    expect(screen.getByText('Aisle 4')).toBeInTheDocument()
    expect(screen.getByText('READY')).toBeInTheDocument()
    expect(screen.getByText('STOPPED')).toBeInTheDocument()
    expect(screen.getAllByText(/amul milk 1l/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText('87%').length).toBeGreaterThan(0)
  })

  it('shows LIVE status and edge stats when the camera runs in the Edge runtime', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM, CAM2], total: 2 },
      '/api/edge/cameras': [
        {
          camera_id: 'c1',
          name: 'Front Counter',
          kind: 'usb',
          running: true,
          connection_ok: true,
          error: null,
          enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
          fps: 12.4,
          frames_captured: 100,
          frames_processed: 90,
          frames_dropped: 10,
          observations_written: 7,
          last_frame_at: null,
          last_event_at: null,
          uptime_seconds: 5,
          started_at: null,
        },
      ],
      '/api/observations': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('LIVE')).toBeInTheDocument()
    expect(screen.getAllByText('RUNNING').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/12\.4 fps/i).length).toBeGreaterThan(0)
  })

  it('shows the empty state when no cameras are configured', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [], total: 0 },
      '/api/cameras': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/no cameras configured/i)).toBeInTheDocument()
  })

  it('isolates a failing camera: one error does not take down the grid', async () => {
    const cam = { ...CAM, camera_type: 'file', config: { kind: 'file' } }
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [cam, CAM2], total: 2 },
      '/api/edge/cameras': [
        {
          camera_id: 'c1',
          name: CAM.name,
          kind: 'file',
          running: true,
          connection_ok: true,
          error: null,
          enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
          fps: 6,
          frames_captured: 10,
          frames_processed: 9,
          frames_dropped: 1,
          observations_written: 2,
          last_frame_at: null,
          last_event_at: null,
          uptime_seconds: 4,
          started_at: null,
        },
        {
          camera_id: 'c2',
          name: CAM2.name,
          kind: 'rtsp',
          running: false,
          connection_ok: false,
          error: 'Failed to open camera source',
          enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
          fps: 0,
          frames_captured: 0,
          frames_processed: 0,
          frames_dropped: 0,
          observations_written: 0,
          last_frame_at: null,
          last_event_at: null,
          uptime_seconds: null,
          started_at: null,
        },
      ],
      '/api/observations': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('LIVE')).toBeInTheDocument()
    expect(screen.getByText('ERROR')).toBeInTheDocument()
    expect(screen.getByText(/failed to open camera source/i)).toBeInTheDocument()
    expect(screen.getByText(CAM.name)).toBeInTheDocument()
    expect(screen.getByText(CAM2.name)).toBeInTheDocument()
  })

  it('still lists configured cameras when the Edge runtime and observations are unreachable', async () => {
    // Only DB-backed endpoints answer; the Edge runtime + observations fail.
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/edge/cameras': [500, { detail: 'runtime offline' }],
      '/api/observations': [500, { detail: 'down' }],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Front Counter')).toBeInTheDocument()
    expect(screen.getByText('READY')).toBeInTheDocument()
    expect(screen.getAllByText(/preview unavailable/i).length).toBeGreaterThan(0)
  })

  it('shows a retryable error state when the backend is entirely unavailable', async () => {
    stubFetchReject()
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/edge node unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})