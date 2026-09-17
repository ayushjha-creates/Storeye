import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge } from '../components/ui/Badge'
import { Card, Stat } from '../components/ui/Card'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import {
  IconRoute,
  IconCamera,
  IconClock,
  IconTarget,
  IconUsers,
  IconShield,
} from '../components/ui/icons'
import { journeyApi } from '../lib/api/journeys'
import { storeApi } from '../lib/api/zone'
import type { JourneyDetail, TimelineEvent } from '../lib/api/types'

// One anonymous shopper journey (M19).
//
// Identity is fully opaque: the global_person_id is a derived hash, the
// timeline shows only camera/zone/stage transitions, and no face, crop,
// embedding, or biometric data is ever returned by the API.

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function shortId(id: string | null | undefined): string {
  if (!id) return '—'
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-6)}` : id
}

const CONFIDENCE_TONE: Record<string, 'green' | 'blue' | 'amber' | 'gray'> = {
  HIGH: 'green',
  MEDIUM: 'blue',
  LOW: 'amber',
  UNKNOWN: 'gray',
}

const EVENT_TONE: Record<string, 'green' | 'blue' | 'amber' | 'purple' | 'gray'> = {
  journey_start: 'green',
  track: 'blue',
  zone_enter: 'amber',
  zone_exit: 'gray',
  transition: 'purple',
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      <span className="absolute left-[5px] top-7 h-full w-px bg-white/[0.08]" aria-hidden="true" />
      <span
        className={`relative mt-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface-100 ${
          event.type === 'journey_start'
            ? 'bg-emerald-400'
            : event.type === 'transition'
              ? 'bg-violet-400'
              : event.type === 'zone_enter'
                ? 'bg-amber-400'
                : 'bg-sky-400'
        }`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={EVENT_TONE[event.type] ?? 'gray'}>{event.type.replace('_', ' ')}</Badge>
          <span className="text-xs text-gray-400">{new Date(event.at).toLocaleString()}</span>
        </div>
        <p className="mt-1 text-sm text-gray-200">{event.detail}</p>
        {(event.camera_name || event.zone_name) && (
          <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-gray-500">
            {event.camera_name && <span>Camera: {event.camera_name}</span>}
            {event.zone_name && <span>Zone: {event.zone_name}</span>}
          </p>
        )}
      </div>
    </li>
  )
}

export function JourneyDetailPage() {
  const { journeyId } = useParams<{ journeyId: string }>()
  const [journey, setJourney] = useState<JourneyDetail | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    if (!journeyId) return
    setLoading(true)
    setError(null)
    try {
      const stores = await storeApi.list()
      const sid = stores.items[0]?.id ?? null
      if (!sid) throw new Error('No store configured')
      const detail = await journeyApi.get(journeyId, { store_id: sid })
      setJourney(detail)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [journeyId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <Spinner label="Loading journey…" />
  if (error && !journey) return <ErrorMessage error={error} onRetry={load} />
  if (!journey) return null

  return (
    <div className="page-shell space-y-6">
      <div>
        <Link to="/app/journeys" className="text-xs font-medium text-cyan-300 hover:underline">
          ← Journeys
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2.5">
          <IconRoute className="h-5 w-5 text-brand-600" />
          <h1 className="font-mono text-base font-semibold tracking-tight">
            {shortId(journey.global_person_id)}
          </h1>
          <Badge tone={journey.status === 'active' ? 'green' : 'gray'}>
            {journey.status === 'active' ? 'ACTIVE' : 'EXPIRED'}
          </Badge>
          <Badge tone={CONFIDENCE_TONE[journey.confidence] ?? 'gray'}>
            {journey.confidence}
          </Badge>
        </div>
        <p className="mt-1 flex items-center gap-1.5 text-xs text-gray-500">
          <IconShield className="h-3.5 w-3.5" />
          Anonymous shopper — identity never stored; only camera/zone paths.
        </p>
      </div>

      {error && journey ? <ErrorMessage error={error} onRetry={load} /> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Duration"
          value={formatDuration(journey.duration_seconds)}
          hint="first → last sighting"
          icon={<IconClock className="h-4 w-4 text-gray-300" />}
        />
        <Stat
          label="Cameras"
          value={journey.camera_count}
          hint={journey.cameras_visited.map((c) => c.name ?? 'unknown').slice(0, 3).join(', ') || 'single camera'}
          icon={<IconCamera className="h-4 w-4 text-gray-300" />}
        />
        <Stat
          label="Zone visits"
          value={journey.zone_visits_total}
          hint={journey.zones_visited.map((z) => z.name ?? 'zone').join(', ') || 'no zones'}
          icon={<IconTarget className="h-4 w-4 text-amber-400" />}
          tone="warning"
        />
        <Stat
          label="Track associations"
          value={journey.track_associations.length}
          hint={`${journey.transitions.length} camera transition(s)`}
          icon={<IconUsers className="h-4 w-4 text-brand-400" />}
          tone="brand"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Journey timeline" subtitle="Stage-by-stage path across store cameras">
            {journey.timeline.length === 0 ? (
              <EmptyState title="No timeline events yet" hint="Journey is still in progress on the edge node." />
            ) : (
              <ul className="pl-1">
                {journey.timeline.map((e, i) => (
                  <TimelineRow key={`${e.at}-${i}`} event={e} />
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Zone visits" subtitle="Dwell inside configured zones">
            {journey.zone_visits.length === 0 ? (
              <p className="text-sm text-gray-500">No zone visits recorded.</p>
            ) : (
              <ul className="divide-y divide-white/[0.05]">
                {journey.zone_visits.map((v, i) => (
                  <li key={`${v.zone_id}-${i}`} className="py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-100">{v.zone_name ?? 'Zone'}</p>
                      <Badge tone={CONFIDENCE_TONE[v.confidence] ?? 'gray'}>{v.confidence}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {new Date(v.entered_at).toLocaleString()}
                      {v.exited_at ? ` → ${new Date(v.exited_at).toLocaleString()}` : ' → still inside'}
                      {v.dwell_seconds != null ? ` · ${formatDuration(v.dwell_seconds)}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Camera transitions" subtitle="Associations inferred across cameras">
            {journey.transitions.length === 0 ? (
              <p className="text-sm text-gray-500">No cross-camera transitions yet.</p>
            ) : (
              <ul className="divide-y divide-white/[0.05]">
                {journey.transitions.map((t, i) => (
                  <li key={`${t.transitioned_at}-${i}`} className="py-2.5">
                    <p className="text-sm text-gray-100">
                      <span className="text-gray-300">{t.from_camera_name ?? 'edge'}</span>
                      <span className="mx-1.5 text-gray-500">→</span>
                      <span className="text-gray-300">{t.to_camera_name ?? 'edge'}</span>
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {new Date(t.transitioned_at).toLocaleString()}
                      {t.time_gap_seconds != null ? ` · gap ${formatDuration(t.time_gap_seconds)}` : ''}
                      {' · '}
                      <Badge tone={CONFIDENCE_TONE[t.confidence] ?? 'gray'}>{t.confidence}</Badge>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}