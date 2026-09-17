import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InsightDetail } from './InsightDetail'
import type { Insight } from '../../lib/api/types'

const STORE_ID = 'aaaabbbb-0000-4000-8000-000000000001'

function insight(overrides: Partial<Insight> = {}): Insight {
  return {
    id: '11111111-0000-4000-8000-000000000001',
    store_id: STORE_ID,
    category: 'inventory',
    insight_type: 'LOW_STOCK',
    severity: 'HIGH',
    status: 'OPEN',
    title: 'Milk (A-1): current stock below reorder level',
    description: 'Current stock 3 units is at or below the reorder level of 5.',
    rule_id: 'inventory.low_stock',
    source_modules: ['inventory'],
    evidence: {
      rule: 'inventory.low_stock',
      summary: ['Milk (A-1): current stock 3 units (reorder level: 5).'],
      sources: [{ source: 'inventory', entity_type: 'product', entity_name: null }],
      metrics: { current_stock: 3, reorder_level: 5 },
    },
    recommended_action: 'Restock Milk (A-1) to at least 20 units.',
    certainty: 'HIGH',
    entity_type: 'product',
    entity_id: 'p1',
    product_id: 'p1',
    shelf_id: null,
    zone_id: null,
    camera_id: null,
    first_detected_at: '2026-09-16T08:00:00Z',
    last_detected_at: '2026-09-16T08:05:00Z',
    expires_at: '2026-09-18T08:00:00Z',
    acknowledged_at: null,
    resolved_at: null,
    expired_at: null,
    created_at: '2026-09-16T08:00:00Z',
    updated_at: '2026-09-16T08:05:00Z',
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InsightDetail', () => {
  it('renders the why behind the insight with summary, metrics and action', () => {
    render(
      <InsightDetail
        insight={insight()}
        onClose={() => {
          /* noop */
        }}
      />,
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Evidence summary')).toBeInTheDocument()
    expect(screen.getByText(/reorder level: 5/i)).toBeInTheDocument()
    expect(screen.getByText('Key metrics')).toBeInTheDocument()
    expect(screen.getByText('current_stock')).toBeInTheDocument()
    expect(screen.getByText('Recommended action')).toBeInTheDocument()
    expect(screen.getByText(/restock milk/i)).toBeInTheDocument()
    expect(screen.getByText('Inventory')).toBeInTheDocument()
    expect(screen.getByText('inventory.low_stock')).toBeInTheDocument()
  })

  it('renders a no-evidence fallback when the evidence blob is null', () => {
    render(
      <InsightDetail insight={insight({ evidence: null })} onClose={() => {}} />,
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByText('Evidence summary')).not.toBeInTheDocument()
    expect(screen.queryByText('Key metrics')).not.toBeInTheDocument()
  })

  it('closes the dialog via the close button', async () => {
    const onClose = vi.fn()
    render(<InsightDetail insight={insight()} onClose={onClose} />)

    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})