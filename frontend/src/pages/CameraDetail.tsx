import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CameraStream } from '../components/camera/CameraStream'
import { DetectionOverlay } from '../components/camera/DetectionOverlay'
import { AnalysisPanel } from '../components/camera/AnalysisPanel'
import { DetectionStats } from '../components/camera/DetectionStats'
import { ObservationTimeline } from '../components/camera/ObservationTimeline'
import { ReIdPanel } from '../components/camera/ReIdPanel'
import { ProductLabelReads } from '../components/camera/ProductLabelReads'
import { ShelfMonitor } from '../components/camera/ShelfMonitor'
import { ShelfRegionEditor } from '../components/camera/ShelfRegionEditor'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { cameraApi } from '../lib/api/cameras'
import { observationApi } from '../lib/api/observations'
import { reconciliationApi } from '../lib/api/reconciliation'
import { edgeApi } from '../lib/api/edge'
import { intelligenceApi } from '../lib/api/intelligence'
import { alertApi } from '../lib/api/alerts'
import { storeApi } from '../lib/api/zone'
import { shelfSnapshotApi } from '../lib/api/shelfSnapshots'
import { Card } from '../components/ui/Card'
import { IconCamera } from '../components/ui/icons'
import type { ShelfOverlayRegion } from '../components/camera/DetectionOverlay'
import type {
  Alert,
  Camera,
  EdgeCameraStatus,
  Observation,
  ObservationSummary,
  ProductIntelligenceRow,
  ShelfIntelligenceRow,
  ShelfSnapshotRow,
  StreamKind,
} from '../lib/api/types'

// Camera detail: LEFT/MAIN live stream + AI overlay, RIGHT analysis panel,
// BOTTOM recent detection timeline. The stream is served by the local Edge
// Runtime (MJPEG) — never uploaded to a cloud.
//
// Stream modes:
//   AI ANNOTATED — live MJPEG from the Edge Runtime with detections drawn in.
//   RAW — the raw configured feed (config.streamUrl) when present.
// The toggle only appears when a raw feed is configured, and both sources
// come from the local node. No fake/fill-in statistics are ever shown.
//
// While the camera is streaming, the page polls the lightweight live data
// (observations + summary + edge status) so freshly-detected observations from
// the Edge Runtime appear without a manual reload. The MJPEG stream is already
// live; before this the counts/FPS were a one-shot snapshot and looked frozen.

const LIVE_REFRESH_MS = 2000

export function CameraDetailPage() {
  const { cameraId } = useParams<{ cameraId: string }>()
  const [camera, setCamera] = useState<Camera | null>(null)
  const [observations, setObservations] = useState<Observation[]>([])
  const [reconSummary, setReconSummary] = useState<{ status: string; count: number }[]>([])
  const [edge, setEdge] = useState<EdgeCameraStatus | null>(null)
  const [summary, setSummary] = useState<ObservationSummary | null>(null)
  const [productIntel, setProductIntel] = useState<ProductIntelligenceRow[]>([])
  const [shelfIntel, setShelfIntel] = useState<ShelfIntelligenceRow[]>([])
  const [shelfSnapshots, setShelfSnapshots] = useState<ShelfSnapshotRow[]>([])
  const [cameraAlerts, setCameraAlerts] = useState<Alert[]>([])
  const [streamMode, setStreamMode] = useState<'ai' | 'raw'>('ai')
  const modeTouched = useRef(false)
  const storeIdRef = useRef<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  // M30: bumped on every live poll so the shelf monitor re-reads snapshots.
  const [shelfRefresh, setShelfRefresh] = useState(0)

  const refreshEdge = useCallback(async (): Promise<EdgeCameraStatus | null> => {
    if (!cameraId) return null
    try {
      const s = await edgeApi.camera(cameraId)
      setEdge(s)
      return s
    } catch {
      // Edge runtime may be offline or not configured — best effort only.
      setEdge(null)
      return null
    }
  }, [cameraId])

  const load = useCallback(async () => {
    if (!cameraId) return
    setLoading(true)
    setError(null)
    try {
      const cam = await cameraApi.get(cameraId)
      setCamera(cam)

      const [obsRes, recRes, summaryRes, edgeStatus] = await Promise.all([
        observationApi.list({ camera_id: cameraId, limit: 200 }),
        reconciliationApi.list(),
        observationApi.summary({ camera_id: cameraId, hours: 24 }).catch(() => null),
        refreshEdge(),
      ])
      setObservations(obsRes.items)
      setSummary(summaryRes)
      setEdge(edgeStatus)

      // M15: per-camera product + shelf intelligence (best effort).
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        sid = stores.items[0]?.id ?? null
      } catch {
        sid = null
      }
      storeIdRef.current = sid
      if (sid) {
        const [pRes, sRes, snapRes] = await Promise.all([
          intelligenceApi.products({ store_id: sid, camera_id: cameraId }),
          intelligenceApi.shelves({ store_id: sid, camera_id: cameraId }),
          shelfSnapshotApi.summary({ store_id: sid, camera_id: cameraId }).catch(() => null),
        ])
        setProductIntel(pRes.items)
        setShelfIntel(sRes.items)
        if (snapRes?.items) setShelfSnapshots(snapRes.items)
      }

      // M16: alerts tied to this camera (best effort).
      if (sid) {
        try {
          const alertRes = await alertApi.list({ store_id: sid, camera_id: cameraId, limit: 10 })
          setCameraAlerts(alertRes.items)
        } catch {
          setCameraAlerts([])
        }
      }

      // Reconciliation summary relevant to this camera's observations.
      const counts = new Map<string, number>()
      for (const r of recRes.items) counts.set(r.status, (counts.get(r.status) ?? 0) + 1)
      setReconSummary([...counts.entries()].map(([status, count]) => ({ status, count })))
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [cameraId, refreshEdge])

  useEffect(() => {
    load()
  }, [load])

  // Lightweight live refresh: only the fast-moving data (observations, summary,
  // edge status). The heavier intelligence/reconciliation/alert reads stay on
  // the initial full load. Best-effort — a transient failure must not blank the
  // page or surface an error banner.
  const refreshLive = useCallback(async () => {
    if (!cameraId) return
    const [obsRes, summaryRes] = await Promise.all([
      observationApi.list({ camera_id: cameraId, limit: 200 }).catch(() => null),
      observationApi.summary({ camera_id: cameraId, hours: 24 }).catch(() => null),
    ])
    if (obsRes) setObservations(obsRes.items)
    if (summaryRes) setSummary(summaryRes)
    await refreshEdge()
    setShelfRefresh((n) => n + 1)
    if (storeIdRef.current) {
      shelfSnapshotApi
        .summary({ store_id: storeIdRef.current, camera_id: cameraId })
        .then((res) => {
          if (res?.items) setShelfSnapshots(res.items)
        })
        .catch(() => {})
    }
  }, [cameraId, refreshEdge])

  useEffect(() => {
    if (loading) return
    const id = window.setInterval(refreshLive, LIVE_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [loading, refreshLive])

  // Keep the default stream mode sensible as camera/edge state lands, but never
  // override an explicit user choice.
  useEffect(() => {
    if (!camera || modeTouched.current) return
    const rawAvailable = typeof camera.config?.streamUrl === 'string'
    setStreamMode(edge?.running ? 'ai' : rawAvailable ? 'raw' : 'ai')
  }, [camera, edge?.running])

  const toggleRun = useCallback(async () => {
    if (!camera) return
    setBusy(true)
    setError(null)
    try {
      if (edge?.running) await edgeApi.stop(camera.id)
      else await edgeApi.start(camera.id)
    } finally {
      setBusy(false)
    }
    // Reflect the new run state (and any observations) immediately; the poller
    // takes over from here.
    await refreshLive()
  }, [camera, edge, refreshLive])

  if (loading) return <Spinner label="Loading camera…" />
  if (error && !camera) return <ErrorMessage error={error} onRetry={load} />
  if (!camera) return null

  const edgeRunning = Boolean(edge?.running)
  // Prefer the backend's canonical health enum; fall back only for old payloads.
  const health =
    edge?.health ??
    (edge ? (edge.running ? (edge.connection_ok ? 'RUNNING' : 'STARTING') : 'STOPPED') : null)
  const healthLabel =
    health === 'RUNNING'
      ? 'AI RUNNING'
      : health === 'DEGRADED'
        ? 'AI DEGRADED'
        : health === 'STARTING'
          ? 'AI CONNECTING'
          : health === 'ERROR'
            ? 'AI ERROR'
            : camera.is_active
              ? 'AI READY'
              : 'STOPPED'
  const healthTone: 'green' | 'amber' | 'red' | 'gray' =
    health === 'RUNNING'
      ? 'green'
      : health === 'DEGRADED' || health === 'STARTING'
        ? 'amber'
        : health === 'ERROR'
          ? 'red'
          : 'gray'
  const rawUrl = (camera.config?.streamUrl as string | undefined) ?? null
  const useAi = streamMode === 'ai'
  const streamUrl = useAi ? (edgeRunning ? edgeApi.streamUrl(camera.id) : null) : rawUrl
  const streamKind: StreamKind = useAi
    ? 'mjpeg'
    : ((camera.config?.streamKind as StreamKind | undefined) ?? 'mjpeg')

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/app/cameras" className="text-xs font-medium text-brand-700 hover:underline">
            ← Cameras
          </Link>
          <div className="mt-1 flex items-center gap-2.5">
            <IconCamera className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">{camera.name}</h1>
          </div>
          <p className="text-sm text-black">
            {camera.location ?? 'Location not set'} · {camera.camera_type}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={healthTone}>{healthLabel}</Badge>
          <button
            onClick={toggleRun}
            disabled={busy}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
              edgeRunning
                ? 'bg-red-600 text-white hover:bg-red-700'
                : 'bg-brand-600 text-white hover:bg-brand-800'
            } disabled:cursor-not-allowed disabled:opacity-50`}
            aria-label={edgeRunning ? 'Stop edge AI' : 'Start edge AI'}
          >
            {busy ? '…' : edgeRunning ? 'Stop' : 'Start'}
          </button>
        </div>
      </div>

      {error && camera ? <ErrorMessage error={error} onRetry={load} /> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* LEFT / MAIN: live stream + AI overlay */}
        <div className="space-y-4 lg:col-span-2">
          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                Live camera stream —{' '}
                {edgeRunning ? (
                  <span className="text-emerald-600">
                    Edge runtime {edge?.fps?.toFixed?.(1) ?? '…'} fps
                  </span>
                ) : (
                  <span className="text-gray-400">not running</span>
                )}
              </p>
              {rawUrl ? (
                <div className="flex overflow-hidden rounded-lg border border-gray-200 text-xs font-medium">
                  <button
                    onClick={() => {
                      modeTouched.current = true
                      setStreamMode('ai')
                    }}
                    className={`px-3 py-1.5 transition-colors ${
                      streamMode === 'ai'
                        ? 'bg-brand-600 text-white'
                        : 'bg-white text-gray-500 hover:bg-gray-50'
                    }`}
                  >
                    AI ANNOTATED
                  </button>
                  <button
                    onClick={() => {
                      modeTouched.current = true
                      setStreamMode('raw')
                    }}
                    className={`px-3 py-1.5 transition-colors ${
                      streamMode === 'raw'
                        ? 'bg-brand-600 text-white'
                        : 'bg-white text-gray-500 hover:bg-gray-50'
                    }`}
                  >
                    RAW
                  </button>
                </div>
              ) : (
                <p className="text-[11px] text-gray-400">
                  AI annotated feed only — no raw stream URL configured for this camera.
                </p>
              )}
            </div>
            <CameraStream
              cameraName={camera.name}
              streamUrl={streamUrl}
              kind={streamKind}
              fallbackMessage={
                streamMode === 'ai'
                  ? 'Start the camera to stream the live, locally-processed Edge Runtime feed (MJPEG). Video never leaves the premises.'
                  : `Raw feed unavailable (${rawUrl ?? 'no URL configured'}).`
              }
            />
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
              AI detection overlay (real observations)
            </p>
            <DetectionOverlay
              observations={observations.slice(0, 24)}
              cameraName={camera.name}
              shelfRegions={(camera.config?.shelf_regions as ShelfOverlayRegion[] | undefined) ?? []}
              shelfSnapshots={shelfSnapshots}
            />
          </div>
        </div>

        {/* RIGHT: AI analysis + shelf monitoring */}
        <div className="space-y-4">
          <AnalysisPanel
            cameraName={camera.name}
            observations={observations}
            reconciliationSummary={reconSummary}
          />
          <ShelfMonitor camera={camera} refreshKey={shelfRefresh} />
          <ProductLabelReads observations={observations} />
        </div>
      </div>

      {/* M15: per-camera product + shelf intelligence & alerts */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="Alerts (this camera)"
          subtitle="Alert rules derived from existing observations — informational only"
          action={
            <Link to="/app/alerts" className="text-xs font-medium text-brand-700 hover:underline">
              View all →
            </Link>
          }
        >
          {cameraAlerts.length === 0 ? (
            <p className="text-sm text-gray-400">
              No alerts for this camera yet. Run “Evaluate now” on the Alerts page.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {cameraAlerts.slice(0, 8).map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <Link to="/app/alerts" className="block truncate text-sm font-medium text-brand-700 hover:underline">
                      {a.title}
                    </Link>
                    <p className="text-xs text-gray-400">
                      {a.alert_type} · {a.status}
                    </p>
                  </div>
                  <Badge
                    tone={a.severity === 'CRITICAL' || a.severity === 'HIGH' ? 'red' : a.severity === 'MEDIUM' ? 'amber' : 'blue'}
                  >
                    {a.severity}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Shelf Intelligence (this camera)"
          subtitle="AI-estimated visible occupancy per configured region"
        >
          {shelfIntel.length === 0 ? (
            <p className="text-sm text-gray-400">
              No shelf_regions configured for this camera.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {shelfIntel.map((r) => (
                <li key={`${r.shelf_code}-${r.camera_id}`} className="py-2">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-gray-800">
                      {r.region_label ?? r.shelf_code}
                    </p>
                    <Badge tone={r.detection_status === 'NORMAL_VISIBLE' ? 'green' : r.detection_status === 'LOW_VISIBLE' ? 'amber' : r.detection_status === 'EMPTY_VISIBLE' ? 'red' : 'gray'}>
                      {r.estimated_visible_occupancy != null
                        ? `${Math.round(r.estimated_visible_occupancy * 100)}% · ${r.detection_status}`
                        : r.detection_status}
                    </Badge>
                  </div>
                  {r.visible_products.length > 0 ? (
                    <p className="mt-0.5 text-xs text-gray-400">
                      {r.visible_products.map((p) => `${p.ai_class} ×${p.visible_count}`).join(', ')}
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs text-gray-400">No product detected.</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Product Intelligence (this camera)"
          subtitle="AI-visible quantity vs recorded inventory — informational only"
        >
          {productIntel.length === 0 ? (
            <p className="text-sm text-gray-400">
              No mapped product observations for this camera in the window.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {productIntel.slice(0, 10).map((r) => (
                <li key={`${r.ai_class}-${r.camera_id}`} className="flex items-center justify-between py-2">
                  <div>
                    <p className="text-sm font-medium text-gray-800">
                      {r.ai_class}
                      {r.mapped && r.product_name ? (
                        <span className="text-gray-500"> → {r.product_name}</span>
                      ) : (
                        <Badge tone="purple" >Unmapped</Badge>
                      )}
                    </p>
                    <p className="text-xs text-gray-400">
                      {r.database_quantity != null ? `DB ${r.database_quantity}` : 'no inventory'} ·{' '}
                      {r.comparison_status}
                    </p>
                  </div>
                  <Badge tone={r.difference != null && r.difference < 0 ? 'red' : r.difference != null && r.difference > 0 ? 'amber' : 'green'}>
                    {r.visible_count} visible · {r.difference != null ? `${r.difference > 0 ? '+' : ''}${r.difference}` : '—'}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* M17: batch metadata is read close-up, not from continuous cameras */}
        <Card
          title="Receive Stock"
          subtitle="Continuous cameras do not read printed expiry / batch / MRP at distance. Use a close-up package photo instead."
          action={
            <Link to="/app/receive" className="text-xs font-medium text-brand-700 hover:underline">
              Receive new stock →
            </Link>
          }
        >
          <p className="text-sm text-gray-600">
            Point a phone at the pack: the local barcode + OCR reads the product,
            batch, MFG, EXP and MRP. You review and confirm the values before any
            stock is moved — nothing is committed automatically.
          </p>
        </Card>
      </div>

      {/* M27: operator-defined shelf regions (no shelf detector exists) */}
      {camera ? (
        <ShelfRegionEditor
          key={camera.updated_at}
          camera={camera}
          latestProductBox={
            observations.find((o) => o.observation_type === 'PRODUCT' && o.bbox)?.bbox ?? null
          }
          onSaved={load}
        />
      ) : null}

      {/* Technical Diagnostics & Telemetry (expandable so it doesn't clutter the store owner's view) */}
      <details className="group rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-all">
        <summary className="flex cursor-pointer items-center justify-between font-semibold text-sm text-gray-700 select-none hover:text-brand-700">
          <span className="flex items-center gap-2">
            <span>🔧</span>
            <span>Advanced Diagnostics & AI Telemetry</span>
          </span>
          <span className="text-xs font-normal text-gray-400 group-open:hidden">
            Click to view FPS, stage timings, raw event feed & person Re-ID
          </span>
        </summary>
        <div className="mt-4 space-y-6 border-t border-gray-100 pt-4">
          <DetectionStats camera={camera} edge={edge} summary={summary} />
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
              Recent detections — {observations.length} in view
            </p>
            <ObservationTimeline observations={observations} onRefresh={load} />
          </div>
          {/* M19: person Re-ID for this camera (anonymous, cross-camera continuity) */}
          <ReIdPanel observations={observations} />
        </div>
      </details>
    </div>
  )
}