import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { ShelfRegionEditor } from './ShelfRegionEditor'
import { stubFetchRoutes } from '../../test/mock'
import type { Camera } from '../../lib/api/types'

const CAM: Camera = {
  id: 'c1',
  store_id: 's1',
  name: 'Entrance Cam',
  location: 'Entrance',
  camera_type: 'usb',
  is_active: true,
  config: {
    kind: 'usb',
    shelf_regions: [{ code: 'A1', label: 'Chips shelf', bbox: [0, 0, 100, 100] }],
  },
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ShelfRegionEditor', () => {
  it('lists the configured shelf regions from the camera config', () => {
    stubFetchRoutes({ '/api/cameras': CAM })
    render(<ShelfRegionEditor camera={CAM} />)

    expect(screen.getByText(/chips shelf/i)).toBeInTheDocument()
    expect(screen.getByText(/\(A1\)/)).toBeInTheDocument()
    expect(screen.getByText(/1 region\(s\)/i)).toBeInTheDocument()
  })

  it('adds a region and saves it into camera.config.shelf_regions', async () => {
    const user = userEvent.setup()
    const fetchMock = stubFetchRoutes({ '/api/cameras': CAM })
    render(<ShelfRegionEditor camera={CAM} />)

    await user.type(screen.getByLabelText('Shelf region code'), 'A2')
    await user.type(screen.getByLabelText('Shelf region label'), 'Biscuit bay')
    await user.type(screen.getByLabelText('Shelf region x1'), '120')
    await user.type(screen.getByLabelText('Shelf region y1'), '30')
    await user.type(screen.getByLabelText('Shelf region x2'), '300')
    await user.type(screen.getByLabelText('Shelf region y2'), '240')
    await user.click(screen.getByRole('button', { name: /add region/i }))

    expect(screen.getByText(/2 region\(s\)/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /save regions/i }))

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/cameras/c1') &&
          (init as RequestInit | undefined)?.method === 'PATCH',
      )
      expect(patched).toBeTruthy()
      const body = JSON.parse(String((patched?.[1] as RequestInit).body))
      expect(body.config.shelf_regions).toHaveLength(2)
      expect(body.config.shelf_regions[1]).toEqual({
        code: 'A2',
        label: 'Biscuit bay',
        bbox: [120, 30, 300, 240],
      })
      // Existing unrelated config keys must be preserved.
      expect(body.config.kind).toBe('usb')
    })
  })

  it('removes a region from the pending list before saving', async () => {
    const user = userEvent.setup()
    stubFetchRoutes({ '/api/cameras': CAM })
    render(<ShelfRegionEditor camera={CAM} />)

    await user.click(screen.getByRole('button', { name: /remove shelf region A1/i }))
    expect(screen.getByText(/0 region\(s\)/i)).toBeInTheDocument()
    expect(screen.queryByText(/chips shelf/i)).not.toBeInTheDocument()
  })
})
