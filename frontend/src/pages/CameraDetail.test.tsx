import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { EdgeProvider } from '../edge/EdgeContext'
import { CameraDetailPage } from './CameraDetail'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const CAMERA_ID = 'aaaabbbb-0000-4000-8000-000000000002'
const PRODUCT_ID = 'aaaabbbb-0000-4000-8000-000000000003'

function detailRoutes(camera: Record<string, unknown>) {
  return {
    '/api/health': { status: 'ok', app: 'storeye', version: '0.1.0' },
    '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    '/api/cameras/': camera,
    '/api/observations': {
      items: [
        {
          id: 'o1',
          observation_type: 'PERSON',
          store_id: STORE_ID,
          camera_id: CAMERA_ID,
          product_id: null,
          track_id: 3,
          confidence: 0.91,
          bbox: [20, 30, 40, 50],
          text: null,
          observed_at: '2026-09-06T10:00:00Z',
        },
        {
          id: 'o2',
          observation_type: 'PRODUCT',
          store_id: STORE_ID,
          camera_id: CAMERA_ID,
          product_id: PRODUCT_ID,
          track_id: null,
          confidence: 0.8,
          bbox: [50, 20, 30, 40],
          text: 'Amul Milk 1L',
          observed_at: '2026-09-06T09:59:00Z',
        },
      ],
      total: 2,
    },
    '/api/products': {
      items: [
        {
          id: PRODUCT_ID,
          store_id: STORE_ID,
          sku: 'AMUL-1L',
          name: 'Amul Milk 1L',
          brand: 'Amul',
          category: 'Dairy',
          unit: 'packet',
          selling_price: '62.00',
          cost_price: '55.00',
          tax_rate: '0.05',
          is_active: true,
        },
      ],
      total: 1,
    },
    '/api/reconciliation': { items: [], total: 0 },
  }
}

const BASE_CAMERA = {
  id: CAMERA_ID,
  store_id: STORE_ID,
  name: 'Front Counter',
  location: 'Entrance',
  camera_type: 'usb',
  is_active: true,
}

function renderDetail(camera: Record<string, unknown>) {
  stubFetchRoutes(detailRoutes(camera))
  return render(
    <EdgeProvider>
      <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
        <Routes>
          <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
        </Routes>
      </MemoryRouter>
    </EdgeProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CameraDetailPage', () => {
  it('lists camera-scoped alerts with a link to the alert inbox', async () => {
    stubFetchRoutes({
      ...detailRoutes({ ...BASE_CAMERA, config: {} }),
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/products': { items: [], total: 0 },
      '/api/intelligence/shelves': { items: [], total: 0 },
      '/api/alerts': {
        items: [
          {
            id: '11111111-0000-4000-8000-000000000001',
            store_id: STORE_ID,
            camera_id: CAMERA_ID,
            product_id: null,
            shelf_id: null,
            alert_type: 'CAMERA_OFFLINE',
            severity: 'MEDIUM',
            status: 'OPEN',
            title: 'No detections from Front Counter',
            message: 'Camera has not produced a detection recently.',
            confidence: 1.0,
            source_type: 'camera_health',
            source_id: null,
            first_detected_at: '2026-09-07T08:00:00Z',
            last_detected_at: '2026-09-07T08:00:00Z',
            acknowledged_at: null,
            resolved_at: null,
            dismissed_at: null,
            details: {},
            created_at: '2026-09-07T08:00:00Z',
            updated_at: '2026-09-07T08:00:00Z',
          },
        ],
        total: 1,
      },
    })
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    expect(await screen.findByText('Alerts (this camera)')).toBeInTheDocument()
    expect(screen.getByText(/no detections from front counter/i)).toBeInTheDocument()
    expect(screen.getByText(/camera_offline · open/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view all →/i })).toHaveAttribute('href', '/app/alerts')
  })

  it('shows the camera, the AI analysis panel and the detection timeline', async () => {
    renderDetail({ ...BASE_CAMERA, config: {} })

    expect(await screen.findByRole('heading', { name: /front counter/i })).toBeInTheDocument()
    expect(screen.getByText('AI ANALYSIS')).toBeInTheDocument()
    expect(screen.getByText(/recent detections — 2 in view/i)).toBeInTheDocument()
    expect(screen.getAllByText('Amul Milk 1L').length).toBeGreaterThan(0)
    expect(screen.getAllByText('PERSON').length).toBeGreaterThan(0)
    expect(screen.getByText('People detected')).toBeInTheDocument()
    expect(screen.getByText('Products detected')).toBeInTheDocument()
  })

  it('renders the stream-unavailable state when no stream endpoint is configured', async () => {
    renderDetail({ ...BASE_CAMERA, config: {} })

    const unavailable = await screen.findByTestId('stream-unavailable')
    expect(unavailable).toHaveTextContent(/camera stream unavailable/i)
  })

  it('renders a real stream container when a streamUrl is configured', async () => {
    renderDetail({ ...BASE_CAMERA, config: { streamUrl: 'http://localhost:8888/mjpeg/live', streamKind: 'mjpeg' } })

    expect(await screen.findByTestId('camera-stream')).toBeInTheDocument()
    expect(screen.queryByTestId('stream-unavailable')).not.toBeInTheDocument()
  })

  it('streams the live Edge MJPEG feed and shows AI RUNNING when the runtime is running', async () => {
    const edgeRunning = {
      camera_id: CAMERA_ID,
      name: 'Front Counter',
      kind: 'usb',
      running: true,
      connection_ok: true,
      error: null,
      enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
      fps: 8.0,
      frames_captured: 100,
      frames_processed: 80,
      frames_dropped: 20,
      observations_written: 12,
      last_frame_at: null,
      last_event_at: null,
      uptime_seconds: 5,
      started_at: null,
    }
    stubFetchRoutes({
      ...detailRoutes({ ...BASE_CAMERA, config: {} }),
      [`/api/edge/cameras/${CAMERA_ID}`]: edgeRunning,
    })
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    expect(await screen.findByText('AI RUNNING')).toBeInTheDocument()
    expect(screen.findByTestId('camera-stream')).toBeTruthy()
    // The stream should point at the local Edge MJPEG endpoint.
    const img = document.querySelector('img[src*="/api/edge/cameras/"]') as HTMLImageElement | null
    expect(img?.src).toContain(`/api/edge/cameras/${CAMERA_ID}/stream`)
    expect(screen.getByText(/8.0 fps/i)).toBeInTheDocument()
  })

  it('starts the camera via the Edge runtime when Start is clicked', async () => {
    const stopped = {
      camera_id: CAMERA_ID,
      name: 'Front Counter',
      kind: 'usb',
      running: false,
      connection_ok: true,
      error: null,
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
    }
    const fetchMock = stubFetchRoutes({
      ...detailRoutes({ ...BASE_CAMERA, config: {} }),
      [`/api/edge/cameras/${CAMERA_ID}`]: stopped,
      [`/api/edge/cameras/${CAMERA_ID}/start`]: {
        camera_id: CAMERA_ID,
        started: true,
        running: true,
      },
    })
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    const startBtn = await screen.findByRole('button', { name: /start edge ai/i })
    await userEvent.click(startBtn)

    // Start was POSTed to the local Edge control endpoint.
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) =>
        String(url).includes(`${CAMERA_ID}/start`) && (init as RequestInit).method === 'POST',
      )).toBe(true)
    })
  })

  it('toggles between the RAW feed and the AI annotated stream', async () => {
    const running = {
      camera_id: CAMERA_ID,
      name: 'Front Counter',
      kind: 'usb',
      running: true,
      connection_ok: true,
      error: null,
      enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
      fps: 8,
      frames_captured: 100,
      frames_processed: 80,
      frames_dropped: 20,
      observations_written: 12,
      last_frame_at: null,
      last_event_at: null,
      uptime_seconds: 5,
      started_at: null,
    }
    const rawUrl = 'http://localhost:8888/mjpeg/raw'
    stubFetchRoutes({
      ...detailRoutes({ ...BASE_CAMERA, config: { streamUrl: rawUrl, streamKind: 'mjpeg' } }),
      [`/api/edge/cameras/${CAMERA_ID}`]: running,
    })
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    const stream = await screen.findByTestId('camera-stream')
    await vi.waitFor(() => {
      // Defaults to the AI annotated edge feed while running.
      const img = stream.querySelector('img') as HTMLImageElement | null
      expect(img?.src).toContain(`/api/edge/cameras/${CAMERA_ID}/stream`)
    })

    await userEvent.click(screen.getByRole('button', { name: 'RAW' }))
    await vi.waitFor(() => {
      const rawImg = document.querySelector('img[src*="/mjpeg/raw"]') as HTMLImageElement | null
      expect(rawImg?.src).toContain(rawUrl)
    })

    await userEvent.click(screen.getByRole('button', { name: 'AI ANNOTATED' }))
    await vi.waitFor(() => {
      const aiImg = document.querySelector(
        `img[src*="/api/edge/cameras/${CAMERA_ID}/stream"]`,
      ) as HTMLImageElement | null
      expect(aiImg?.src).toContain('/api/edge/cameras/')
    })
  })

  it('polls live so newly-detected observations appear without a manual refresh', async () => {
    const initial = detailRoutes({ ...BASE_CAMERA, config: {} })
    const routes: Record<string, unknown> = { ...initial }
    stubFetchRoutes(routes)
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    expect(await screen.findByText(/2 in view/i)).toBeInTheDocument()

    // A new real observation lands in the backend after the page was opened.
    routes['/api/observations'] = {
      items: [
        ...initial['/api/observations'].items,
        {
          id: 'o3',
          observation_type: 'PERSON',
          store_id: STORE_ID,
          camera_id: CAMERA_ID,
          product_id: null,
          track_id: 4,
          confidence: 0.88,
          bbox: [10, 10, 30, 60],
          text: null,
          observed_at: '2026-09-06T10:01:00Z',
        },
      ],
      total: 3,
    }

    // The poller (2s) must surface it without any user action.
    await vi.waitFor(
      () => expect(screen.getByText(/3 in view/i)).toBeInTheDocument(),
      { timeout: 3000, interval: 100 },
    )
  })

  it('shows the AI runtime as unavailable when the Edge runtime is unreachable', async () => {
    renderDetail({ ...BASE_CAMERA, config: {} })

    expect(
      await screen.findByText(/ai runtime status not available/i),
    ).toBeInTheDocument()
  })

  it('truthfully flags when product detection is not enabled for the camera', async () => {
    const stopped = {
      camera_id: CAMERA_ID,
      name: 'Front Counter',
      kind: 'usb',
      running: false,
      connection_ok: true,
      error: null,
      enabled_pipelines: { person_detection: true, product_detection: false, ocr: false },
      fps: 0,
      frames_captured: 0,
      frames_processed: 0,
      frames_dropped: 0,
      observations_written: 0,
      last_frame_at: null,
      last_event_at: null,
      uptime_seconds: null,
      started_at: null,
    }
    stubFetchRoutes({
      ...detailRoutes({ ...BASE_CAMERA, config: {} }),
      [`/api/edge/cameras/${CAMERA_ID}`]: stopped,
    })
    render(
      <EdgeProvider>
        <MemoryRouter initialEntries={[`/cameras/${CAMERA_ID}`]}>
          <Routes>
            <Route path="/cameras/:cameraId" element={<CameraDetailPage />} />
          </Routes>
        </MemoryRouter>
      </EdgeProvider>,
    )

    expect(
      await screen.findByText(/product detection is not enabled for this camera/i),
    ).toBeInTheDocument()
  })
})