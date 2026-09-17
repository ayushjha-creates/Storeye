import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Observation } from '../../lib/api/types'
import { ReIdPanel } from './ReIdPanel'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'
const CAMERA_ID = 'aaaabbbb-0000-4000-8000-000000000002'

function person(
  id: string,
  over: Partial<Observation> = {},
): Observation {
  return {
    id,
    observation_type: 'PERSON',
    store_id: STORE_ID,
    camera_id: CAMERA_ID,
    product_id: null,
    batch_id: null,
    track_id: 1,
    frame_number: 5,
    source: 'edge:file:test.mp4',
    confidence: 0.9,
    bbox: [10, 10, 60, 120],
    text: null,
    source_observation_id: null,
    observed_at: '2026-09-10T10:01:00Z',
    details: { global_person_id: 'gp-alice', reid_confidence: 'HIGH' },
    created_at: '2026-09-10T10:01:00Z',
    updated_at: '2026-09-10T10:01:00Z',
    ...over,
  }
}

describe('ReIdPanel', () => {
  it('renders the anonymous connection warning', () => {
    render(<ReIdPanel observations={[]} />)
    expect(screen.getByText(/cross-camera continuity key/i)).toBeInTheDocument()
  })

  it('shows the empty state when there are no associations yet', () => {
    render(<ReIdPanel observations={[]} />)
    expect(
      screen.getByText(/no anonymous person associations yet/i),
    ).toBeInTheDocument()
  })

  it('maps a local track id to an anonymous global person id', () => {
    render(
      <ReIdPanel
        observations={[
          person('obs1', { track_id: 3, details: { global_person_id: 'gp-alice', reid_confidence: 'MEDIUM' } }),
        ]}
      />,
    )
    expect(screen.getByText('#3')).toBeInTheDocument()
    expect(screen.getByText(/gp-ali/)).toBeInTheDocument()
    expect(screen.getByText('MEDIUM')).toBeInTheDocument()
  })

  it('deduplicates per track, keeping the latest observation', () => {
    render(
      <ReIdPanel
        observations={[
          person('obs-old', {
            track_id: 7,
            observed_at: '2026-09-10T10:00:00Z',
            details: { global_person_id: 'gp-bob', reid_confidence: 'LOW' },
          }),
          person('obs-new', {
            track_id: 7,
            observed_at: '2026-09-10T10:30:00Z',
            details: { global_person_id: 'gp-bob', reid_confidence: 'HIGH' },
          }),
        ]}
      />,
    )
    expect(screen.getAllByText('#7')).toHaveLength(1)
    expect(screen.getByText('HIGH')).toBeInTheDocument()
  })

  it('ignores non-person observations entirely', () => {
    render(
      <ReIdPanel
        observations={[
          person('obs1', {
            observation_type: 'PRODUCT',
            track_id: null,
            details: null,
          }),
        ]}
      />,
    )
    expect(screen.getByText(/no anonymous person associations yet/i)).toBeInTheDocument()
  })
})