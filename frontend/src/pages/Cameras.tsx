import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { IconCamera } from '../components/ui/icons'
import { cameraApi } from '../lib/api/cameras'
import { observationApi } from '../lib/api/observations'
import { edgeApi, byCameraId, edgeStatusForCamera } from '../lib/api/edge'
import type {
  Camera,
  EdgeCameraStatus,
  Observation,
  ObservationSummary,
} from '../lib/api/types'
import { storeApi } from '../lib/api/zone'

// Camera overview grid.
//
// Every figure shown here comes from the REAL API layer: DB cameras from
// GET /api/cameras, live Edge runtime stats from GET /api/edge/cameras, and
// detection aggregates from GET /api/observations/summary (last 24h). There
// are NO hardcoded/fake camera numbers. One failing camera/edge fetch must
// not prevent the rest of the grid from rendering — each lookup is isolated.

type Health = { tone: 'green' | 'amber' | 'red' | 'blue'; label: string }

function cameraHealth(c: Camera, edge: EdgeCameraStatus | null): Health {
  if (edge) {
    if (edge.running && edge.connection_ok) return { tone: 'green', label: 'LIVE' }
    if (edge.running) return { tone: 'amber', label: 'CONNECTING' }
    if (edge.error) return { tone: 'red', label: 'ERROR' }
  }
  return c.is_active
    ? { tone: 'blue', label: 'READY' }
    : { tone: 'red', label: 'STOPPED' }
}

function typeCount(summary: ObservationSummary | null | undefined, type: string): number {
  return summary?.by_type?.[type] ?? 0
}

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [latestByCamera, setLatestByCamera] = useState<Record<string, Observation | null>>({})
  const [summaries, setSummaries] = useState<Record<string, ObservationSummary | null>>({})
  const [edgeByCamera, setEdgeByCamera] = useState<Map<string, EdgeCameraStatus>>(new Map())
  const [edgeOnline, setEdgeOnline] = useState(false)
  const [previewFailed, setPreviewFailed] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        sid = stores.items[0]?.id ?? null
      } catch {
        sid = null
      }
      const camRes = await cameraApi.list(sid ? { store_id: sid } : undefined)
      setCameras(camRes.items)

      // Best-effort Edge runtime status (failures -> empty map, grid still works).
      try {
        const edgeList = await edgeApi.cameras()
        setEdgeByCamera(byCameraId(edgeList))
        setEdgeOnline(true)
      } catch {
        setEdgeByCamera(new Map())
        setEdgeOnline(false)
      }

      // Per-camera latest observation and 24h aggregate — each isolated.
      const perCamera: Record<string, Observation | null> = {}
      const perSummary: Record<string, ObservationSummary | null> = {}
      await Promise.all(
        camRes.items.map(async (c) => {
          try {
            const obs = await observationApi.list({ camera_id: c.id, limit: 1 })
            perCamera[c.id] = obs.items[0] ?? null
          } catch {
            perCamera[c.id] = null
          }
          try {
            perSummary[c.id] = await observationApi.summary({ camera_id: c.id, hours: 24 })
          } catch {
            perSummary[c.id] = null
          }
        }),
      )
      setLatestByCamera(perCamera)
      setSummaries(perSummary)
    } catch (err) {
      setError(err)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // Gentle refresh so the grid reflects a camera that just started/stopped.
    const id = setInterval(() => load(true), 30_000)
    return () => clearInterval(id)
  }, [load])

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <IconCamera className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">Cameras</h1>
          </div>
          <p className="mt-0.5 text-sm text-black">
            Edge AI camera feeds — processed locally, never uploaded to the cloud
          </p>
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={() => load()} /> : null}

      {loading ? (
        <Spinner label="Loading cameras…" />
      ) : (
        <Card title="Configured Cameras" subtitle={`${cameras.length} camera(s)`}>
          {cameras.length === 0 ? (
            <EmptyState
              title="No cameras configured"
              hint="Add cameras through the API (POST /api/cameras), then this dashboard will show live status."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {cameras.map((c) => {
                const latest = latestByCamera[c.id]
                const edge = edgeStatusForCamera(c, edgeByCamera)
                const running = Boolean(edge?.running)
                const health = cameraHealth(c, edge)
                const summary = summaries[c.id]
                return (
                  <Link
                    key={c.id}
                    to={`/app/cameras/${c.id}`}
                    className="group flex flex-col rounded-xl border border-gray-200 bg-surface-200 p-4 shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-brand-500/40 hover:shadow-md"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate font-medium text-gray-900 group-hover:text-brand-700">
                        {c.name}
                      </p>
                      <Badge tone={health.tone}>{health.label}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {c.location ?? 'Location not set'} · {c.camera_type}
                    </p>

                    {/* Live preview thumbnail (real Edge MJPEG) — placeholder otherwise. */}
                    <div className="relative mt-3 h-28 overflow-hidden rounded-lg bg-black">
                      {running && edgeOnline ? (
                        !previewFailed[c.id] ? (
                          <img
                            src={edgeApi.streamUrl(c.id)}
                            alt={`Live preview: ${c.name}`}
                            className="h-full w-full object-cover"
                            onError={() => setPreviewFailed((p) => ({ ...p, [c.id]: true }))}
                          />
                        ) : (
                          <div className="flex h-full items-center justify-center px-3 text-center text-[11px] text-gray-400">
                            Stream preview not loading — open the camera for the live feed
                          </div>
                        )
                      ) : (
                        <div className="flex h-full items-center justify-center px-3 text-center text-[11px] text-gray-400">
                          Preview unavailable —{' '}
                          {running ? 'edge feed still connecting' : 'start Edge AI to preview'}
                        </div>
                      )}
                    </div>

                    {edge?.error ? (
                      <p className="mt-2 rounded-lg bg-red-50 px-3 py-1.5 text-[11px] text-red-600">
                        {edge.error}
                      </p>
                    ) : null}

                    <div className="mt-3 flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                      <span className="text-xs font-medium text-gray-500">AI processing</span>
                      <Badge tone={running ? 'green' : 'blue'}>{running ? 'RUNNING' : 'IDLE'}</Badge>
                    </div>
                    {running && (
                      <div className="mt-1 flex items-center justify-between rounded-lg bg-gray-50 px-3 py-1.5">
                        <span className="text-[11px] text-gray-400">Edge feed</span>
                        <span className="text-[11px] font-medium text-gray-600">
                          {edge?.fps?.toFixed?.(1) ?? '…'} fps · {edge?.observations_written ?? 0} obs
                        </span>
                      </div>
                    )}

                    <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                      <div className="rounded-lg bg-gray-50 px-2 py-2">
                        <p className="text-sm font-bold text-gray-900">
                          {running ? typeCount(summary, 'PERSON') : '—'}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-gray-400">
                          people (24h)
                        </p>
                      </div>
                      <div className="rounded-lg bg-gray-50 px-2 py-2">
                        <p className="text-sm font-bold text-gray-900">
                          {running ? typeCount(summary, 'PRODUCT') : '—'}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-gray-400">
                          products (24h)
                        </p>
                      </div>
                    </div>

                    <div className="mt-2">
                      <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                        Latest observation
                      </p>
                      {latest ? (
                        <>
                          <div className="mt-1 flex items-center gap-2">
                            <Badge tone="blue">{latest.observation_type}</Badge>
                            {latest.confidence != null && (
                              <span className="text-xs text-gray-400">
                                {Math.round(latest.confidence * 100)}%
                              </span>
                            )}
                          </div>
                          <p className="mt-1 truncate text-xs text-gray-600">
                            {latest.text ?? `${latest.observation_type} detection`}
                          </p>
                          <p className="mt-0.5 text-[11px] text-gray-400">
                            {new Date(latest.observed_at).toLocaleString()}
                          </p>
                        </>
                      ) : (
                        <p className="mt-1 text-xs text-gray-400">No AI detections yet</p>
                      )}
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}