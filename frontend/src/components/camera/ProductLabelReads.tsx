import { Badge } from '../ui/Badge'
import type { Observation } from '../../lib/api/types'

// Camera OCR product-label reads.
//
// Shows the most recent package text the camera OCR read (product name,
// MFG/EXP dates, MRP) and, when the store catalog matched the printed name,
// the mapped product + its catalog price. This is ASSISTIVE ONLY: it is an
// observation, never an inventory change, and unmatched labels are labelled
// "Unrecognized label" rather than guessed.

interface ProductLabelReadsProps {
  observations: Observation[]
  /** Maximum number of reads to show (most recent first). */
  limit?: number
}

function detailString(details: Record<string, unknown> | null, key: string): string | null {
  const value = details?.[key]
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number') return String(value)
  return null
}

function formatMoney(value: string | null): string | null {
  if (!value) return null
  const num = Number(value)
  if (!Number.isFinite(num)) return value
  return `₹${num.toFixed(2)}`
}

function formatDate(value: string | null): string | null {
  if (!value) return null
  // Stored as an ISO date; show the date portion only.
  return value.slice(0, 10)
}

export function ProductLabelReads({ observations, limit = 5 }: ProductLabelReadsProps) {
  const reads = observations
    .filter((o) => o.observation_type === 'EXPIRY_METADATA')
    .slice()
    .sort((a, b) => (a.observed_at < b.observed_at ? 1 : -1))
    .slice(0, limit)

  return (
    <div className="rounded-xl border border-gray-200 bg-surface-200 shadow-sm">
      <header className="border-b border-gray-100 px-4 py-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          Product label reads (OCR)
        </p>
        <p className="mt-0.5 text-xs text-gray-500">
          Read from the live camera · assistive only, never changes stock
        </p>
      </header>

      {reads.length === 0 ? (
        <p className="px-4 py-4 text-sm text-gray-400">
          No label reads yet. Enable “Read product labels (OCR)” for this camera and hold a package
          up to it.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {reads.map((o) => {
            const name = detailString(o.details, 'recognized_product_name')
            const mfg = formatDate(detailString(o.details, 'manufacturing_date'))
            const exp = formatDate(detailString(o.details, 'expiry_date'))
            const precision = detailString(o.details, 'expiry_date_precision')
            const labelMrp = formatMoney(detailString(o.details, 'mrp'))
            const catalogPrice = formatMoney(detailString(o.details, 'catalog_price'))
            const confidence =
              typeof o.confidence === 'number' ? `${Math.round(o.confidence * 100)}%` : '—'
            return (
              <li key={o.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-semibold text-gray-900">
                    {name ?? 'Unrecognized label'}
                  </p>
                  {name ? (
                    <Badge tone="green">Matched catalog</Badge>
                  ) : (
                    <Badge tone="amber">Not in catalog</Badge>
                  )}
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-gray-400">MFG</dt>
                    <dd className="text-gray-700">{mfg ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-400">EXP</dt>
                    <dd className="text-gray-700">
                      {exp ?? '—'}
                      {exp && precision === 'month' ? ' (month)' : ''}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-400">MRP (label)</dt>
                    <dd className="text-gray-700">{labelMrp ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-400">Catalog price</dt>
                    <dd className="text-gray-700">{catalogPrice ?? '—'}</dd>
                  </div>
                </dl>
                <p className="mt-1 text-[11px] text-gray-400">
                  OCR confidence {confidence} · {new Date(o.observed_at).toLocaleString()}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
