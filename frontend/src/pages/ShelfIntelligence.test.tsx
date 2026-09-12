import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ShelfIntelligencePage } from './ShelfIntelligence'
import { stubFetchRoutes } from '../test/mock'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

const SHELVES = [
  {
    shelf_code: 'A1',
    region_label: 'Aisle A top',
    shelf_id: 's1',
    zone_id: 'z1',
    zone_name: 'Snacks',
    camera_id: 'c1',
    camera_name: 'Shelf Cam',
    bbox: [0, 0, 100, 100],
    detection_status: 'NORMAL_VISIBLE',
    estimated_visible_occupancy: 0.55,
    occupied_pct: 55,
    visible_products: [
      { ai_class: 'Lays', product_id: 'p1', product_name: 'Lays Classic', sku: 'LAYS-1', visible_count: 3, confidence: 0.9, counting_rule: 'max_simultaneous_per_frame', expected_on_shelf: true, possible_misplacement: false },
      { ai_class: 'Maggi', product_id: 'p2', product_name: 'Maggi', sku: 'MAGGI-2', visible_count: 1, confidence: 0.85, counting_rule: 'max_simultaneous_per_frame', expected_on_shelf: false, possible_misplacement: true },
    ],
    latest_observed_at: '2026-09-07T08:00:00Z',
    mean_confidence: 0.9,
    last_analysis_message: 'AI-estimated visible occupancy from associated product detections (informational; not stock).',
  },
  {
    shelf_code: 'B2',
    region_label: null,
    shelf_id: null,
    zone_id: null,
    zone_name: null,
    camera_id: 'c1',
    camera_name: 'Shelf Cam',
    bbox: [200, 0, 300, 100],
    detection_status: 'UNKNOWN',
    estimated_visible_occupancy: null,
    occupied_pct: null,
    visible_products: [],
    latest_observed_at: null,
    mean_confidence: null,
    last_analysis_message: 'No AI data in window (camera offline or pipeline off).',
  },
]

const SUMMARY = {
  computed_at: '2026-09-07T08:00:00Z',
  window_hours: 24,
  cameras: { total: 1, active: 1, ai_running: 1, ai_stopped: 0, regions_configured: 1 },
  people: { distinct_tracks: 0, last_observed_at: null },
  products: { visible_classes: 2, mapped_classes: 2, unmapped_classes: 0, total_visible_quantity: 4 },
  shelves: { regions_configured: 2, with_ai_data: 1, empty_visible: 0, low_visible: 0, normal_visible: 1, unknown: 1, possible_misplacements: 1 },
  reconciliation: { possible_shortages: 0, possible_surpluses: 0, review_required: 0, total_last_window: 0 },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ShelfIntelligencePage', () => {
  it('renders occupancy, states and misplaced-product flags', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/summary': SUMMARY,
      '/api/intelligence/shelves': { items: SHELVES, total: 2 },
    })
    render(
      <MemoryRouter>
        <ShelfIntelligencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /shelf intelligence/i })).toBeInTheDocument()
    expect(screen.getByText(/Aisle A top/)).toBeInTheDocument()
    // 55% occupancy rendered.
    expect(screen.getByText('55%')).toBeInTheDocument()
    expect(screen.getByText('OK (visible)')).toBeInTheDocument()
    expect(screen.getByText('Unknown — no AI data')).toBeInTheDocument()
    expect(screen.getByText('possible misplaced')).toBeInTheDocument()
    expect(screen.getByText(/occupancy unavailable|Unavailable/)).toBeInTheDocument()
  })

  it('shows empty state when no shelf regions are configured', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/summary': SUMMARY,
      '/api/intelligence/shelves': { items: [], total: 0 },
    })
    render(
      <MemoryRouter>
        <ShelfIntelligencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/no shelf regions configured/i)).toBeInTheDocument()
  })

  it('links to related low-shelf and misplacement open alerts', async () => {
    stubFetchRoutes({
      '/api/stores': { items: [{ id: STORE_ID, name: 'Store' }], total: 1 },
      '/api/intelligence/summary': SUMMARY,
      '/api/intelligence/shelves': { items: SHELVES, total: 2 },
      '/api/alerts': {
        items: [
          {
            id: '11111111-0000-4000-8000-000000000001',
            store_id: STORE_ID,
            camera_id: 'c1',
            product_id: null,
            shelf_id: 's1',
            alert_type: 'LOW_SHELF_OCCUPANCY',
            severity: 'MEDIUM',
            status: 'OPEN',
            title: 'Low shelf occupancy: Aisle A top',
            message: 'AI-estimated occupancy is below the low-shelf threshold.',
            confidence: 0.7,
            source_type: 'shelf_intelligence',
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
      <MemoryRouter>
        <ShelfIntelligencePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/1 related open alert/i)).toBeInTheDocument()
    expect(screen.getByText('View in Alerts →')).toBeInTheDocument()
    expect(screen.getByText(/low shelf occupancy: aisle a top/i)).toBeInTheDocument()
  })
})