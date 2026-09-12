import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { EdgeProvider } from '../../edge/EdgeContext'
import { CameraStream } from './CameraStream'
import { stubFetchRoutes, stubFetchReject } from '../../test/mock'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CameraStream', () => {
  it('shows the explicit stream-unavailable state when the edge is online but no URL is set', async () => {
    stubFetchRoutes({
      '/api/health': { status: 'ok' },
      '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    })
    render(
      <EdgeProvider>
        <CameraStream cameraName="Front Counter" fallbackMessage="No stream endpoint yet." />
      </EdgeProvider>,
    )
    const el = await screen.findByTestId('stream-unavailable')
    expect(el).toHaveTextContent(/camera stream unavailable/i)
    expect(el).toHaveTextContent(/no stream endpoint yet/i)
  })

  it('explains the edge node is offline when it cannot be reached', async () => {
    stubFetchReject()
    render(
      <EdgeProvider>
        <CameraStream cameraName="Front Counter" />
      </EdgeProvider>,
    )
    const el = await screen.findByTestId('stream-unavailable')
    expect(el).toHaveTextContent(/edge node is offline/i)
  })

  it('mounts a live stream container when a stream URL is configured', async () => {
    stubFetchRoutes({
      '/api/health': { status: 'ok' },
      '/api/ready': { ready: true, database: 'postgres', stores: 1 },
    })
    render(
      <EdgeProvider>
        <CameraStream
          cameraName="Front Counter"
          streamUrl="http://localhost:8888/mjpeg/live"
          kind="mjpeg"
        />
      </EdgeProvider>,
    )
    expect(await screen.findByTestId('camera-stream')).toBeInTheDocument()
    expect(screen.queryByTestId('stream-unavailable')).not.toBeInTheDocument()
  })
})