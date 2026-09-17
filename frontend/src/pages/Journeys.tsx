import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '../components/ui/Badge'
import { Card, Stat } from '../components/ui/Card'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import {
  IconRoute,
  IconClock,
  IconCamera,
  IconUsers,
  IconTarget,
  IconActivity,
} from '../components/ui/icons'
import { journeyApi } from '../lib/api/journeys'
import { storeApi } from '../lib/api/zone'
import type { JourneyItem, JourneySummary } from '../lib/api/types'

// Anonymous Customer Journeys (M19).
//
// Every row is keyed by an OPAQUE global_person_id — a deterministic hash of
// appearance embeddings, never a name, face, or biometric. Cross-camera
// continuity only: we know where a shopper went, not WHO they are.

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-6)}` : id
}

const CONFIDENCE_TONE: Record<string, 'green' | 'blue' | 'amber' | 'gray'> = {
  HIGH: 'green',
  MEDIUM: 'blue',
  LOW: 'amber',
  UNKNOWN: 'gray',
}

export function JourneysPage() {
  const [summary, setSummary] = useState<JourneySummary | null>(null)
  const [journeys, setJourneys] = useState<JourneyItem[]>([])
  const [total, setTotal] = useState(0)
  const [confidence, setConfidence] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const stores = await storeApi.list()
      const sid = stores.items[0]?.id ?? null
      if (!sid) {
        setSummary(null)
        setJourneys([])
        setTotal(0)
        return
      }
      const [sumRes, listRes] = await Promise.all([
        journeyApi.summary({ store_id: sid }),
        journeyApi.list({
          store_id: sid,
          limit: 200,
          ...(confidence ? { confidence } : {}),
        }),
      ])
      setSummary(sumRes)
      setJourneys(listRes.items)
      setTotal(listRes.total)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [confidence])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <IconRoute className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">Customer Journeys</h1>
          </div>
          <p className="mt-0.5 text-sm text-gray-500">
            Anonymous, cross-camera shopper paths — re-identification by appearance only
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-gray-500">
            Confidence
            <select
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-2.5 py-1.5 text-sm text-gray-100 focus:border-brand-500/60 focus:outline-none"
            >
              <option value="">Any</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
              <option value="UNKNOWN">UNKNOWN</option>
            </select>
          </label>
          <button onClick={load} className="btn-secondary" disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat
          label="Total visitors"
          value={summary?.total_visitors ?? 0}
          hint="in selected window"
          icon={<IconUsers className="h-4 w-4 text-brand-400" />}
          tone="brand"
        />
        <Stat
          label="Currently active"
          value={summary?.active_visitors ?? 0}
          hint="shopping right now"
          icon={<IconActivity className="h-4 w-4 text-emerald-400" />}
          tone="positive"
        />
        <Stat
          label="Avg visit"
          value={formatDuration(summary?.avg_visit_duration_seconds)}
          hint="from first to last sighting"
          icon={<IconClock className="h-4 w-4 text-gray-300" />}
        />
        <Stat
          label="Avg zone dwell"
          value={formatDuration(summary?.avg_zone_dwell_seconds)}
          hint="per zone visit"
          icon={<IconTarget className="h-4 w-4 text-gray-300" />}
        />
        <Stat
          label="Zone visits"
          value={summary?.total_zone_visits ?? 0}
          hint={
            summary?.most_visited_zone?.name
              ? `busiest: ${summary.most_visited_zone.name}`
              : 'across all zones'
          }
          icon={<IconRoute className="h-4 w-4 text-amber-400" />}
          tone="warning"
        />
      </div>

      <Card
        title="Anonymous journeys"
        subtitle="Opaque person IDs, never names or faces — local processing only"
        action={
          <Link to="/app/cameras" className="text-xs font-medium text-brand-700 hover:underline">
            Cameras →
          </Link>
        }
      >
        {loading ? (
          <Spinner label="Loading journeys…" />
        ) : journeys.length === 0 ? (
          <EmptyState
            title={error ? 'No journey data available' : 'No journeys recorded yet'}
            hint="Journeys appear once the Edge runtime associates people across two or more cameras. Enable Re-ID in camera configs and keep cameras running."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-white/[0.06] text-xs uppercase tracking-wide text-gray-500">
                  <th className="px-4 py-2.5 font-medium">Person</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Confidence</th>
                  <th className="px-4 py-2.5 font-medium">First seen</th>
                  <th className="px-4 py-2.5 font-medium">Duration</th>
                  <th className="px-4 py-2.5 font-medium">Cameras</th>
                  <th className="px-4 py-2.5 font-medium">Zones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.05]">
                {journeys.map((j) => (
                  <tr key={j.global_person_id} className="hover:bg-white/[0.03]">
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/app/journeys/${encodeURIComponent(j.global_person_id)}`}
                        className="font-mono text-[13px] font-medium text-cyan-300 hover:underline"
                        title={j.global_person_id}
                      >
                        {shortId(j.global_person_id)}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={j.status === 'active' ? 'green' : 'gray'}>
                        {j.status === 'active' ? 'ACTIVE' : 'EXPIRED'}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={CONFIDENCE_TONE[j.confidence] ?? 'gray'}>{j.confidence}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-gray-400">
                      {new Date(j.first_seen_at).toLocaleString()}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-gray-300">
                      {formatDuration(j.duration_seconds)}
                    </td>
                    <td className="px-4 py-2.5 text-gray-300">
                      <span className="inline-flex items-center gap-1">
                        <IconCamera className="h-3.5 w-3.5 text-gray-500" />
                        {j.camera_count} ·{' '}
                        {j.cameras_visited.map((c) => c.name ?? 'unknown').slice(0, 2).join(', ')}
                        {j.cameras_visited.length > 2 ? ` +${j.cameras_visited.length - 2}` : ''}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-300">
                      {j.zones_visited.length === 0 ? (
                        <span className="text-gray-500">—</span>
                      ) : (
                        j.zones_visited
                          .map((z) => `${z.name ?? 'zone'}${z.visits > 1 ? ` ×${z.visits}` : ''}`)
                          .join(', ')
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 px-4 text-xs text-gray-500">
              {total} journey(s) · matching the selected confidence filter
            </p>
          </div>
        )}
      </Card>
    </div>
  )
}