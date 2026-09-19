import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ShelfMonitor } from './ShelfMonitor'
import { stubFetchRoutes } from '../../test/mock'
import type { Camera, ShelfSnapshotSummary } from '../../lib/api/types'

const CAM: Camera = {
  id: 'c1',
  store_id: 's1',
  name: 'Entrance Cam',
  location: null,
  camera_type: 'usb',
  is_active: true,
  config: null,
  created_at: '',
  updated_at: '',
}

function summary(overrides: Partial<ShelfSnapshotSummary> = {}): ShelfSnapshotSummary {
  return {
    total_regions: 2,
    last_scan_at: '2026-09-18T10:00:30Z',
    status: { EMPTY: 0, LOW: 1, MEDIUM: 0, FULL: 1, OCCLUDED: 0 },
    items: [
      {
        id: 'a',
        store_id: 's1',
        camera_id: 'c1',
        shelf_code: 'A',
        shelf_label: 'Biscuits wall',
        region_bbox: null,
        snapshot_path: null,
        crop_path: null,
        has_image: false,
        fill_percentage: 82.5,
        status: 'FULL',
        product_count: 4,
        occluded: false,
        occlusion_note: null,
        confidence: 0.85,
        observed_at: '2026-09-18T10:00:30Z',
        created_at: null,
      },
      {
        id: 'b',
        store_id: 's1',
        camera_id: 'c1',
        shelf_code: 'B',
        shelf_label: 'Front endcap',
        region_bbox: null,
        snapshot_path: null,
        crop_path: null,
        has_image: false,
        fill_percentage: 22.75,
        status: 'LOW',
        product_count: 1,
        occluded: false,
        occlusion_note: null,
        confidence: 0.78,
        observed_at: '2026-09-18T10:00:30Z',
        created_at: null,
      },
    ],
    ...overrides,
  }
}

describe('ShelfMonitor', () => {
  it('renders configured regions with real fill badges', async () => {
    stubFetchRoutes({ '/api/shelf-snapshots/summary': summary() })
    render(<ShelfMonitor camera={CAM} />)

    expect(await screen.findByText('Biscuits wall')).toBeInTheDocument()
    expect(screen.getByText('Front endcap')).toBeInTheDocument()
    expect(screen.getByText('83% · Full')).toBeInTheDocument()
    expect(screen.getByText('23% · Half or less')).toBeInTheDocument()
    expect(screen.getByText(/Last scan/)).toBeInTheDocument()
    // Status counts footer.
    expect(screen.getByText('Low: 1')).toBeInTheDocument()
    expect(screen.getByText('Full: 1')).toBeInTheDocument()
  })

  it('shows an honest empty state when no snapshots exist yet', async () => {
    stubFetchRoutes({
      '/api/shelf-snapshots/summary': {
        total_regions: 0,
        last_scan_at: null,
        status: { EMPTY: 0, LOW: 0, MEDIUM: 0, FULL: 0, OCCLUDED: 0 },
        items: [],
      },
    })
    render(<ShelfMonitor camera={CAM} />)

    expect(await screen.findByText(/no shelf snapshots yet/i)).toBeInTheDocument()
  })

  it('flags an occluded region instead of reporting misleading fill', async () => {
    stubFetchRoutes({
      '/api/shelf-snapshots/summary': summary({
        status: { EMPTY: 0, LOW: 0, MEDIUM: 0, FULL: 0, OCCLUDED: 1 },
        items: [
          {
            id: 'c',
            store_id: 's1',
            camera_id: 'c1',
            shelf_code: 'C',
            shelf_label: null,
            region_bbox: null,
            snapshot_path: null,
            crop_path: null,
            has_image: false,
            fill_percentage: 22.75,
            status: 'LOW',
            product_count: 1,
            occluded: true,
            occlusion_note: 'Person blocking',
            confidence: null,
            observed_at: '2026-09-18T10:05:00Z',
            created_at: null,
          },
        ],
      }),
    })
    render(<ShelfMonitor camera={CAM} />)

    expect(await screen.findByText('OCCLUDED')).toBeInTheDocument()
    expect(screen.getByText(/Person blocking/)).toBeInTheDocument()
    // No misleading fill bar for an occluded region.
    expect(screen.queryByTestId('fill-bar-C')).toBeNull()
  })

  it('shows an error state when the snapshot API fails', async () => {
    stubFetchRoutes({ '/api/shelf-snapshots/summary': [500, { detail: 'boom' }] })
    render(<ShelfMonitor camera={CAM} />)

    expect(await screen.findByText(/boom/)).toBeInTheDocument()
  })
})