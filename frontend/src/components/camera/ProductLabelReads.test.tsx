import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ProductLabelReads } from './ProductLabelReads'
import type { Observation } from '../../lib/api/types'

function obs(overrides: Partial<Observation>): Observation {
  return {
    id: 'o1',
    observation_type: 'EXPIRY_METADATA',
    store_id: 's1',
    camera_id: 'c1',
    product_id: null,
    batch_id: null,
    track_id: null,
    frame_number: 1,
    source: null,
    confidence: 0.91,
    bbox: null,
    text: 'Amul Taaza Milk\nEXP 12/09/2027',
    source_observation_id: null,
    observed_at: '2026-09-06T10:00:00Z',
    details: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('ProductLabelReads', () => {
  it('renders a matched label with name, dates and prices', () => {
    render(
      <ProductLabelReads
        observations={[
          obs({
            id: 'read-1',
            product_id: 'p1',
            details: {
              recognized_product_name: 'Amul Taaza Milk',
              manufacturing_date: '2026-01-01',
              expiry_date: '2027-09-12',
              expiry_date_precision: 'day',
              mrp: '54.00',
              catalog_price: '52.00',
            },
          }),
        ]}
      />,
    )
    expect(screen.getByText('Amul Taaza Milk')).toBeInTheDocument()
    expect(screen.getByText('Matched catalog')).toBeInTheDocument()
    expect(screen.getByText('2026-01-01')).toBeInTheDocument()
    expect(screen.getByText('2027-09-12')).toBeInTheDocument()
    expect(screen.getByText('₹54.00')).toBeInTheDocument()
    expect(screen.getByText('₹52.00')).toBeInTheDocument()
  })

  it('labels an unmatched read as unrecognized instead of guessing', () => {
    render(
      <ProductLabelReads
        observations={[
          obs({
            id: 'read-2',
            details: { expiry_date: '2027-01-31', mrp: '10.00' },
          }),
        ]}
      />,
    )
    expect(screen.getByText('Unrecognized label')).toBeInTheDocument()
    expect(screen.getByText('Not in catalog')).toBeInTheDocument()
    expect(screen.getByText('₹10.00')).toBeInTheDocument()
  })

  it('shows an honest empty state when OCR produced no reads', () => {
    render(<ProductLabelReads observations={[obs({ observation_type: 'PERSON' })]} />)
    expect(screen.getByText(/no label reads yet/i)).toBeInTheDocument()
  })
})
