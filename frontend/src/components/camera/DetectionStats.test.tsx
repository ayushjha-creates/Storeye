import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DetectionStats } from './DetectionStats'
import type { Camera, EdgeCameraStatus, ObservationSummary } from '../../lib/api/types'

const CAMERA: Camera = {
  id: 'c1',
  store_id: 's1',
  name: 'Front Counter',
  location: 'Entrance',
  camera_type: 'usb',
  is_active: true,
  config: {},
  created_at: '',
  updated_at: '',
}

const EDGE_RUNNING: EdgeCameraStatus = {
  camera_id: 'c1',
  name: 'Front Counter',
  kind: 'usb',
  running: true,
  connection_ok: true,
  error: null,
  enabled_pipelines: { person_detection: true, product_detection: true, ocr: false },
  fps: 7.5,
  frames_captured: 1000,
  frames_processed: 800,
  frames_dropped: 200,
  observations_written: 34,
  last_frame_at: '2026-09-06T10:00:00Z',
  last_event_at: '2026-09-06T10:00:05Z',
  uptime_seconds: 90,
  started_at: '2026-09-06T09:58:00Z',
}

const EDGE_IDLE: EdgeCameraStatus = { ...EDGE_RUNNING, running: false, fps: 0, frames_captured: 0, frames_processed: 0, frames_dropped: 0, observations_written: 0, uptime_seconds: null }

const SUMMARY: ObservationSummary = {
  total: 10,
  by_type: { PERSON: 6, PRODUCT: 3, TEXT: 1, EXPIRY_METADATA: 0 },
  distinct_tracks: 2,
  avg_confidence: 0.8,
  last_observed_at: '2026-09-06T10:00:00Z',
  activity: [{ bucket_ts: '2026-09-06T09:00:00Z', count: 10 }],
}

describe('DetectionStats', () => {
  it('says explicitly that runtime status is unavailable without edge data', () => {
    render(<DetectionStats camera={CAMERA} edge={null} summary={null} />)
    expect(screen.getByText(/ai runtime status not available/i)).toBeInTheDocument()
    // Never substitutes fake statistics for missing data.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('shows Not available for performance counters when no frames flowed', () => {
    render(<DetectionStats camera={CAMERA} edge={EDGE_IDLE} summary={null} />)
    expect(screen.getAllByText(/not available/i).length).toBeGreaterThan(1)
  })

  it('renders the real 24h aggregate numbers and the activity chart', () => {
    render(<DetectionStats camera={CAMERA} edge={EDGE_RUNNING} summary={SUMMARY} />)
    expect(screen.getByText('10')).toBeInTheDocument() // detections total
    expect(screen.getByText('6')).toBeInTheDocument() // people
    expect(screen.getByText('3')).toBeInTheDocument() // products
    expect(screen.getByText('80%')).toBeInTheDocument() // avg confidence
    expect(screen.getByText('2')).toBeInTheDocument() // tracked people
    // Live throughput counters instead of fake labels.
    expect(screen.getByText('7.5')).toBeInTheDocument()
    expect(screen.getByText('20%')).toBeInTheDocument() // drop rate 200/1000
  })

  it('truthfully notes when product detection is disabled in the pipeline', () => {
    const edge = { ...EDGE_RUNNING, enabled_pipelines: { ...EDGE_RUNNING.enabled_pipelines, product_detection: false } }
    render(<DetectionStats camera={CAMERA} edge={edge} summary={SUMMARY} />)
    expect(screen.getByText(/product detection is not enabled for this camera/i)).toBeInTheDocument()
    // Avoids a fake zero when the pipeline is simply off.
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})