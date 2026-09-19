import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  vi.restoreAllMocks()
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

  it('renders the backend canonical health enum when present', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM, CAM2], total: 2 },
      '/api/edge/cameras': [
        {
          camera_id: 'c1',
          name: CAM.name,
          kind: 'usb',
          running: true,
          connection_ok: false,
          error: null,
          health: 'STARTING',
          enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
          fps: 0,
          frames_captured: 0,
          frames_processed: 0,
          frames_dropped: 0,
          observations_written: 0,
          last_frame_at: null,
          last_event_at: null,
          uptime_seconds: 1,
          started_at: null,
        },
        {
          camera_id: 'c2',
          name: CAM2.name,
          kind: 'rtsp',
          running: false,
          connection_ok: false,
          error: null,
          health: 'DISABLED',
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

    expect(await screen.findByText('CONNECTING')).toBeInTheDocument()
    expect(screen.getByText('DISABLED')).toBeInTheDocument()
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

    expect(await screen.findByText(/set up your first camera/i)).toBeInTheDocument()
  })

  it('quick-starts a 1-camera template with a real, pipeline-shaped config', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [], total: 0 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [500, { detail: 'runtime offline' }],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: '1 camera' }))

    await waitFor(() => {
      const created = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith('/api/cameras') &&
          (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(created).toBeTruthy()
      const body = JSON.parse(String((created![1] as RequestInit).body))
      expect(body.name).toBe('Entrance Cam')
      // Pipelines are written in the nested shape the Edge runtime reads.
      expect(body.config.pipelines).toEqual({ person_detection: true, product_detection: true })
      expect(body.config.fps_cap).toBe(0)
    })
  })

  it('warns when running cameras reach the configured capacity', async () => {
    const running = (id: string, name: string) => ({
      camera_id: id,
      name,
      kind: 'usb',
      running: true,
      connection_ok: true,
      error: null,
      health: 'RUNNING',
      enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
      fps: 5,
      frames_captured: 10,
      frames_processed: 9,
      frames_dropped: 1,
      observations_written: 1,
      last_frame_at: null,
      last_event_at: null,
      uptime_seconds: 3,
      started_at: null,
    })
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': {
        items: [CAM, CAM2],
        total: 2,
      },
      '/api/edge/cameras': [running('c1', CAM.name), running('c2', CAM2.name)],
      '/api/edge/status': {
        running: true,
        cameras: 2,
        max_cameras: 2,
        started_at: null,
      },
      '/api/observations': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/ai processing capacity limited/i)).toBeInTheDocument()
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

  it('provisions a new camera from the grid', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /add camera/i }))
    await user.type(screen.getByLabelText('Camera name'), 'Stockroom Cam')
    await user.type(screen.getByLabelText('Camera location'), 'Back room')
    await user.click(screen.getByRole('button', { name: /create camera/i }))

    await waitFor(() => {
      const created = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith('/api/cameras') &&
          (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(created).toBeTruthy()
    })
  })

  it('edits a camera and saves the changes', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM, CAM2], total: 2 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /edit front counter/i }))
    const name = screen.getByLabelText('Camera name')
    await user.clear(name)
    await user.type(name, 'Entrance Cam')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/cameras/c1') &&
          (init as RequestInit | undefined)?.method === 'PATCH',
      )
      expect(patched).toBeTruthy()
    })
  })

  it('persists the OCR pipeline toggle in the nested config shape', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /edit front counter/i }))
    await user.click(screen.getByLabelText('Read product labels (OCR)'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/cameras/c1') &&
          (init as RequestInit | undefined)?.method === 'PATCH',
      )
      expect(patched).toBeTruthy()
      const body = JSON.parse(String((patched![1] as RequestInit).body))
      expect(body.config.pipelines.ocr).toBe(true)
    })
  })

  it('persists the product detector choice and open-vocab prompts', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /edit front counter/i }))
    await user.selectOptions(screen.getByLabelText('Product detector'), 'shelf')
    await user.type(
      screen.getByLabelText('Product prompts'),
      'biscuit packet, milk carton',
    )
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/cameras/c1') &&
          (init as RequestInit | undefined)?.method === 'PATCH',
      )
      expect(patched).toBeTruthy()
      const body = JSON.parse(String((patched![1] as RequestInit).body))
      expect(body.config.pipelines.product_detector).toBe('shelf')
      expect(body.config.pipelines.product_prompts).toEqual([
        'biscuit packet',
        'milk carton',
      ])
    })
  })

  it('deletes a camera after confirmation', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /delete front counter/i }))

    await waitFor(() => {
      const deleted = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/cameras/c1') &&
          (init as RequestInit | undefined)?.method === 'DELETE',
      )
      expect(deleted).toBeTruthy()
    })
  })

  it('starts one camera without touching the others', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM, CAM2], total: 2 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
    })
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /start front counter/i }))

    await waitFor(() => {
      const started = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/edge/cameras/c1/start') &&
          (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(started).toBeTruthy()
      const otherStarts = fetchMock.mock.calls.filter(([url]) =>
        String(url).includes('/api/edge/cameras/c2/start'),
      )
      expect(otherStarts.length).toBe(0)
    })
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

  it('renders the CCTV Detection Lab and starts sample footage', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
      '/api/edge/demo-sample': {
        camera_id: 'c-demo-1',
        name: 'Demo CCTV — Customer Flow',
        running: true,
        filename: 'test_people.mp4',
        size: 1024,
        source: '/path/test_people.mp4',
        note: 'Demo camera started with sample footage',
      },
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('CCTV Detection Lab')).toBeInTheDocument()
    const sampleBtn = screen.getByRole('button', { name: /customer flow/i })
    expect(sampleBtn).toBeInTheDocument()

    await user.click(sampleBtn)

    expect(await screen.findByText(/started!/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /watch live stream & detections/i })).toBeInTheDocument()
  })

  it('allows picking a CCTV file and starting detection', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/cameras': { items: [CAM], total: 1 },
      '/api/observations': { items: [], total: 0 },
      '/api/edge/cameras': [],
      '/api/edge/demo-video': {
        camera_id: 'c-demo-upload',
        name: 'Demo — my_cctv',
        running: true,
        filename: 'my_cctv.mp4',
        size: 2048,
        source: '/data/demo_videos/my_cctv.mp4',
        note: 'Demo camera created and started',
      },
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CamerasPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('CCTV Detection Lab')).toBeInTheDocument()
    const fileInput = screen.getByLabelText(/upload cctv footage/i) as HTMLInputElement

    const testFile = new File(['fake-mp4-data'], 'my_cctv.mp4', { type: 'video/mp4' })
    await user.upload(fileInput, testFile)

    expect(await screen.findByText(/my_cctv\.mp4/i)).toBeInTheDocument()
    const startBtn = screen.getByRole('button', { name: /start detection on this clip/i })
    await user.click(startBtn)

    expect(await screen.findByText(/demo camera "demo — my_cctv" started!/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /watch live stream & detections/i })).toHaveAttribute(
      'href',
      '/app/cameras/c-demo-upload',
    )
  })
})