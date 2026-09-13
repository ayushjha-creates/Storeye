import { Badge } from '../ui/Badge'
import type { Observation } from '../../lib/api/types'

// Reusable AI analysis panel.
//
// Aggregates REAL M11 observation data for a camera/store. No fake AI
// conclusions: every figure below is derived from stored observations.
// Reconciliation figures come from the reconciliation API results.

interface AnalysisPanelProps {
  cameraName?: string
  observations: Observation[]
  reconciliationSummary?: { status: string; count: number }[]
}

export function AnalysisPanel({
  cameraName,
  observations,
  reconciliationSummary = [],
}: AnalysisPanelProps) {
  const people = observations.filter((o) => o.observation_type === 'PERSON')
  const products = observations.filter((o) => o.observation_type === 'PRODUCT')
  const textObs = observations.filter((o) => o.observation_type === 'TEXT')
  const expiryObs = observations.filter(
    (o) => o.observation_type === 'EXPIRY_METADATA',
  )

  const distinctTracks = new Set(people.map((o) => o.track_id).filter((t) => t != null)).size

  // Product observations keyed by product id, showing latest count text.
  const productCounts = products.reduce<Record<string, number>>((acc, o) => {
    const key = o.text ?? o.product_id ?? 'unknown'
    const val = typeof o.details?.observed === 'number' ? (o.details.observed as number) : 1
    acc[key] = (acc[key] ?? 0) + val
    return acc
  }, {})

  const expiryWarnings = expiryObs.filter(
    (o) => typeof o.details?.status === 'string' &&
      (o.details.status === 'EXPIRING_SOON' || o.details.status === 'EXPIRED'),
  ).length

  const ReconRow = ({ item }: { item: { status: string; count: number } }) => {
    const tone =
      item.status === 'MATCH'
        ? 'green'
        : item.status === 'POSSIBLE_SHORTAGE'
          ? 'red'
          : item.status === 'POSSIBLE_SURPLUS'
            ? 'amber'
            : 'purple'
    return (
      <div className="flex items-center justify-between py-1">
        <Badge tone={tone}>{item.status}</Badge>
        <span className="text-xs text-gray-500">{item.count} product(s)</span>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-surface-200 shadow-sm">
      <header className="border-b border-gray-100 px-4 py-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {cameraName ? 'AI ANALYSIS' : 'AI ANALYSIS'}
        </p>
        <p className="mt-0.5 text-sm font-semibold text-gray-900">{cameraName ?? 'Live feed'}</p>
      </header>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-4 text-sm">
        <div>
          <p className="text-xs text-gray-500">People detected</p>
          <p className="text-xl font-bold text-gray-900">{people.length}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Products detected</p>
          <p className="text-xl font-bold text-gray-900">{products.length}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Tracked people</p>
          <p className="text-xl font-bold text-gray-900">{distinctTracks}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">OCR events</p>
          <p className="text-xl font-bold text-gray-900">{textObs.length}</p>
        </div>
      </div>

      <div className="border-t border-gray-100 px-4 py-3">
        <p className="text-xs font-semibold text-gray-500">Expiry information</p>
        <p className="mt-1 text-sm text-gray-700">
          {expiryObs.length === 0
            ? 'No expiry metadata detected yet'
            : `${expiryObs.length} product(s) with expiry detected`}
        </p>
        {expiryWarnings > 0 && (
          <p className="text-sm text-amber-700">
            {expiryWarnings} approaching/expired
          </p>
        )}
      </div>

      <div className="border-t border-gray-100 px-4 py-3">
        <p className="text-xs font-semibold text-gray-500">Inventory observation</p>
        {Object.keys(productCounts).length === 0 ? (
          <p className="mt-1 text-sm text-gray-400">No product observations yet</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {Object.entries(productCounts)
              .slice(0, 6)
              .map(([key, count]) => (
                <li key={key} className="flex items-center justify-between text-sm">
                  <span className="truncate text-gray-700">{key}</span>
                  <span className="ml-2 text-gray-500">{count} observed</span>
                </li>
              ))}
          </ul>
        )}
      </div>

      <div className="border-t border-gray-100 px-4 py-3">
        <p className="text-xs font-semibold text-gray-500">Reconciliation</p>
        {reconciliationSummary.length === 0 ? (
          <p className="mt-1 text-sm text-gray-400">Run reconciliation to compare AI vs stock</p>
        ) : (
          <div className="mt-1 divide-y divide-gray-50">
            {reconciliationSummary.map((r) => (
              <ReconRow key={r.status} item={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}