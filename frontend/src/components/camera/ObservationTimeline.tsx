import { useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import { EmptyState } from '../ui/ErrorState'
import type { Observation, ObservationType } from '../../lib/api/types'
import { OBSERVATION_TYPES } from '../../lib/api/types'

interface TimelineProps {
  observations: Observation[]
  loading?: boolean
  onRefresh?: () => void
}

export function ObservationTimeline({
  observations,
  loading = false,
  onRefresh,
}: TimelineProps) {
  const [filter, setFilter] = useState<ObservationType | 'ALL'>('ALL')
  const [minConfidence, setMinConfidence] = useState<number | null>(null)
  const [minConfEnabled, setMinConfEnabled] = useState(false)

  const filtered = useMemo(() => {
    let list = observations
    if (filter !== 'ALL') list = list.filter((o) => o.observation_type === filter)
    if (minConfEnabled && minConfidence != null) {
      list = list.filter((o) => (o.confidence ?? 0) >= minConfidence)
    }
    return list
  }, [observations, filter, minConfidence, minConfEnabled])

  const badgeTone = (type: string) =>
    type === 'PERSON' ? 'amber' : type === 'PRODUCT' ? 'green' : type === 'TEXT' ? 'blue' : 'purple'

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setFilter('ALL')}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              filter === 'ALL' ? 'bg-brand-700 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            All
          </button>
          {OBSERVATION_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setFilter(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                filter === t ? 'bg-brand-700 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <label className="ml-auto flex items-center gap-1.5 text-xs text-gray-500">
          <input
            type="checkbox"
            checked={minConfEnabled}
            onChange={(e) => setMinConfEnabled(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-gray-300 text-brand-600"
          />
          Confidence ≥
          <select
            value={minConfidence ?? 0}
            disabled={!minConfEnabled}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="rounded border border-gray-300 px-1 py-0.5 text-xs disabled:opacity-50"
          >
            <option value={0}>any</option>
            <option value={0.5}>50%</option>
            <option value={0.7}>70%</option>
            <option value={0.9}>90%</option>
          </select>
        </label>

        {onRefresh && (
          <button
            onClick={onRefresh}
            className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200"
          >
            Refresh
          </button>
        )}
      </div>

      {loading ? (
        <p className="py-6 text-center text-sm text-gray-400">Loading timeline…</p>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No observations match"
          hint="Adjust the filters, or run the Edge AI runtime to start recording detections."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-surface-200">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Text</th>
                <th className="px-4 py-2.5 font-medium">Product</th>
                <th className="px-4 py-2.5 font-medium">Confidence</th>
                <th className="px-4 py-2.5 font-medium">Track</th>
                <th className="px-4 py-2.5 font-medium">BBox</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.slice(0, 60).map((o) => (
                <tr key={o.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-2 text-gray-500">
                    {new Date(o.observed_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">
                    <Badge tone={badgeTone(o.observation_type)}>{o.observation_type}</Badge>
                  </td>
                  <td className="max-w-[220px] truncate px-4 py-2 text-gray-700">
                    {o.text ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-gray-500">
                    {o.product_id ? o.product_id.slice(0, 8) + '…' : '—'}
                  </td>
                  <td className="px-4 py-2 text-gray-500">
                    {o.confidence != null ? `${Math.round(o.confidence * 100)}%` : '—'}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{o.track_id ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {o.bbox && o.bbox.length === 4
                      ? `${o.bbox.map((v) => Math.round(v)).join(', ')}`
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}