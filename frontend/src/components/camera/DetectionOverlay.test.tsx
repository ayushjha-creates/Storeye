import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DetectionOverlay } from './DetectionOverlay'
import type { Observation } from '../../lib/api/types'

function obs(overrides: Partial<Observation>): Observation {
  return {
    id: 'o1',
    observation_type: 'PERSON',
    store_id: 's1',
    camera_id: 'c1',
    product_id: null,
    batch_id: null,
    track_id: 7,
    frame_number: 1,
    source: null,
    confidence: 0.9,
    bbox: null,
    text: null,
    source_observation_id: null,
    observed_at: '2026-09-06T10:00:00Z',
    details: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('DetectionOverlay', () => {
  it('renders a backend bbox_norm [x1,y1,x2,y2] in 0..1 as percentages', () => {
    render(
      <DetectionOverlay
        observations={[
          obs({ details: { bbox_norm: [0.25, 0.1, 0.75, 0.6] } }),
        ]}
      />,
    )
    const box = screen.getByTestId('detection-box')
    expect(box).toHaveStyle({ left: '25%', top: '10%', width: '50%', height: '50%' })
  })

  it('falls back to legacy normalized (x,y,w,h) boxes for demo data', () => {
    render(
      <DetectionOverlay observations={[obs({ bbox: [10, 20, 30, 40] })]} />,
    )
    const box = screen.getByTestId('detection-box')
    expect(box).toHaveStyle({ left: '10%', top: '20%', width: '30%', height: '40%' })
  })

  it('ignores zero-size boxes and shows the empty state', () => {
    render(
      <DetectionOverlay
        observations={[obs({ bbox: [10, 20, 0, 40], details: null })]}
      />,
    )
    expect(screen.queryByTestId('detection-box')).not.toBeInTheDocument()
    expect(screen.getByText(/no detections to draw/i)).toBeInTheDocument()
  })
})
