import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, Modal } from '../components/ui/Modal'
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

// The backend now reports one canonical `health` enum. It takes precedence;
// older/partial responses fall back to a derivation so the grid never blanks.
function cameraHealth(c: Camera, edge: EdgeCameraStatus | null): Health {
  switch (edge?.health) {
    case 'RUNNING':
      return { tone: 'green', label: 'LIVE' }
    case 'DEGRADED':
      return { tone: 'amber', label: 'DEGRADED' }
    case 'STARTING':
      return { tone: 'amber', label: 'CONNECTING' }
    case 'ERROR':
      return { tone: 'red', label: 'ERROR' }
    case 'DISABLED':
      return { tone: 'red', label: 'DISABLED' }
    case 'STOPPED':
      return c.is_active
        ? { tone: 'blue', label: 'READY' }
        : { tone: 'red', label: 'STOPPED' }
    default:
      if (edge) {
        if (edge.running && edge.connection_ok) return { tone: 'green', label: 'LIVE' }
        if (edge.running) return { tone: 'amber', label: 'CONNECTING' }
        if (edge.error) return { tone: 'red', label: 'ERROR' }
      }
      return c.is_active
        ? { tone: 'blue', label: 'READY' }
        : { tone: 'red', label: 'STOPPED' }
  }
}

function typeCount(summary: ObservationSummary | null | undefined, type: string): number {
  return summary?.by_type?.[type] ?? 0
}

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

interface CameraForm {
  name: string
  location: string
  cameraType: string
  source: string
  sourceIndex: string
  isActive: boolean
  personDetection: boolean
  productDetection: boolean
  ocr: boolean
  productDetector: string
  productPrompts: string
  fpsCap: string
}

const EMPTY_FORM: CameraForm = {
  name: '',
  location: '',
  cameraType: 'usb',
  source: '',
  sourceIndex: '0',
  isActive: true,
  personDetection: true,
  productDetection: true,
  ocr: false,
  productDetector: 'world',
  productPrompts: '',
  fpsCap: '0',
}

const STARTER_CAMERAS: { name: string; location: string }[] = [
  { name: 'Entrance Cam', location: 'Entrance' },
  { name: 'Aisle Cam', location: 'Aisle' },
  { name: 'Billing Cam', location: 'Billing' },
  { name: 'Back Room Cam', location: 'Back Room' },
]

function formFromCamera(c: Camera): CameraForm {
  const cfg = (c.config ?? {}) as Record<string, unknown>
  const pipelines = (cfg.pipelines ?? {}) as Record<string, unknown>
  return {
    name: c.name,
    location: c.location ?? '',
    cameraType: c.camera_type,
    source: typeof cfg.source === 'string' ? cfg.source : '',
    sourceIndex: String(cfg.source_index ?? 0),
    isActive: c.is_active,
    personDetection: pipelines.person_detection !== false,
    productDetection: pipelines.product_detection !== false,
    ocr: pipelines.ocr === true,
    productDetector:
      typeof pipelines.product_detector === 'string' ? pipelines.product_detector : 'world',
    productPrompts: Array.isArray(pipelines.product_prompts)
      ? (pipelines.product_prompts as string[]).join(', ')
      : '',
    fpsCap: String(cfg.fps_cap ?? 0),
  }
}

export function CamerasPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [latestByCamera, setLatestByCamera] = useState<Record<string, Observation | null>>({})
  const [summaries, setSummaries] = useState<Record<string, ObservationSummary | null>>({})
  const [edgeByCamera, setEdgeByCamera] = useState<Map<string, EdgeCameraStatus>>(new Map())
  const [edgeOnline, setEdgeOnline] = useState(false)
  const [edgeMax, setEdgeMax] = useState<number | null>(null)
  const [previewFailed, setPreviewFailed] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  // Provisioning (M27): create/edit/delete + start/stop from the grid.
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Camera | null>(null)
  const [form, setForm] = useState<CameraForm>(EMPTY_FORM)
  const [formError, setFormError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const [busyCamera, setBusyCamera] = useState<string | null>(null)

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
      setStoreId(sid)
      const camRes = await cameraApi.list(sid ? { store_id: sid } : undefined)
      setCameras(camRes.items)

      // Best-effort Edge runtime status (failures -> empty map, grid still works).
      try {
        const edgeList = await edgeApi.cameras()
        setEdgeByCamera(byCameraId(edgeList))
        setEdgeOnline(true)
        try {
          setEdgeMax((await edgeApi.status()).max_cameras)
        } catch {
          setEdgeMax(null)
        }
      } catch {
        setEdgeByCamera(new Map())
        setEdgeOnline(false)
        setEdgeMax(null)
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

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setFormOpen(true)
  }

  // M27 Phase 17: 1/2/3/4/4+ quick-start templates. These create REAL DB rows
  // with clearly-named starter cameras; the operator points each at a source.
  const addStarterSet = async (count: number) => {
    if (!storeId) return
    setBusyCamera('*')
    setError(null)
    try {
      for (let i = 0; i < count; i++) {
        const t = STARTER_CAMERAS[i]
        await cameraApi.create({
          store_id: storeId,
          name: t.name,
          location: t.location,
          camera_type: 'usb',
          is_active: true,
          config: {
            kind: 'usb',
            source_index: i,
            pipelines: { person_detection: true, product_detection: true },
            fps_cap: 0,
          },
        })
      }
      await load(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusyCamera(null)
    }
  }

  const openEdit = (c: Camera) => {
    setEditing(c)
    setForm(formFromCamera(c))
    setFormError(null)
    setFormOpen(true)
  }

  const saveCamera = async () => {
    if (!storeId || !form.name.trim()) return
    setSaving(true)
    setFormError(null)
    const config: Record<string, unknown> = {
      kind: form.cameraType,
      pipelines: {
        person_detection: form.personDetection,
        product_detection: form.productDetection,
        ocr: form.ocr,
        product_detector: form.productDetector,
        product_prompts: form.productPrompts
          .split(/[,\n]/)
          .map((s) => s.trim())
          .filter(Boolean),
      },
      fps_cap: Number(form.fpsCap) || 0,
    }
    if (form.cameraType === 'usb') config.source_index = Number(form.sourceIndex) || 0
    else if (form.source.trim()) config.source = form.source.trim()

    try {
      if (editing) {
        await cameraApi.update(editing.id, {
          name: form.name.trim(),
          location: form.location.trim() || null,
          camera_type: form.cameraType,
          is_active: form.isActive,
          config,
        })
      } else {
        await cameraApi.create({
          store_id: storeId,
          name: form.name.trim(),
          location: form.location.trim() || null,
          camera_type: form.cameraType,
          is_active: form.isActive,
          config,
        })
      }
      setFormOpen(false)
      await load(true)
    } catch (err) {
      setFormError(err)
    } finally {
      setSaving(false)
    }
  }

  const deleteCamera = async (c: Camera) => {
    if (!window.confirm(`Delete camera “${c.name}”? This removes its configuration.`)) return
    setBusyCamera(c.id)
    try {
      await cameraApi.remove(c.id)
      await load(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusyCamera(null)
    }
  }

  const toggleRunning = async (c: Camera, running: boolean) => {
    setBusyCamera(c.id)
    try {
      if (running) await edgeApi.stop(c.id)
      else await edgeApi.start(c.id)
      await load(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusyCamera(null)
    }
  }

  const startAll = async () => {
    setBusyCamera('*')
    try {
      for (const c of cameras) {
        if (!c.is_active) continue
        try {
          await edgeApi.start(c.id)
        } catch {
          // One camera failing to start must not block the others.
        }
      }
      await load(true)
    } finally {
      setBusyCamera(null)
    }
  }

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <IconCamera className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">Cameras</h1>
          </div>
          <p className="mt-0.5 text-sm text-black">
            Your cameras watch locally — nothing is sent to the cloud.{' '}
            <Link to="/app/live-store" className="text-brand-600 underline decoration-brand-200 hover:text-brand-700">
              Watch your store →
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {cameras.some((c) => c.is_active) ? (
            <Button kind="secondary" onClick={startAll} disabled={busyCamera === '*'}>
              {busyCamera === '*' ? 'Starting…' : 'Start all'}
            </Button>
          ) : null}
          <Button kind="primary" onClick={openCreate} disabled={!storeId}>
            Add camera
          </Button>
        </div>
      </div>

      {edgeOnline &&
      edgeMax != null &&
      edgeMax > 0 &&
      cameras.filter((c) => edgeStatusForCamera(c, edgeByCamera)?.running).length >= edgeMax ? (
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-900">
          <p className="font-medium">AI processing capacity limited</p>
          <p className="text-xs text-amber-700">
            This edge node is configured for at most {edgeMax} camera(s). Stop one before starting
            another, or raise EDGE_MAX_CAMERAS.
          </p>
        </div>
      ) : null}

      {error ? <ErrorMessage error={error} onRetry={() => load()} /> : null}

      <DemoCctvSection
        storeId={storeId}
        onCameraCreated={() => load(true)}
      />

      {loading ? (
        <Spinner label="Loading cameras…" />
      ) : (
        <Card title="Your cameras" subtitle={`${cameras.length} set up`}>
          {cameras.length === 0 ? (
            <EmptyState
              title="Set up your first camera"
              hint="Start with 1, 2, 3 or more — we'll create sensible defaults you can change."
              action={
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {[1, 2, 3, 4].map((n) => (
                    <Button
                      key={n}
                      kind="secondary"
                      onClick={() => addStarterSet(n)}
                      disabled={!storeId || busyCamera === '*'}
                    >
                      {n} camera{n > 1 ? 's' : ''}
                    </Button>
                  ))}
                  <Button
                    kind="secondary"
                    onClick={() => addStarterSet(4)}
                    disabled={!storeId || busyCamera === '*'}
                  >
                    4+ (add more later)
                  </Button>
                </div>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {cameras.map((c) => {
                const latest = latestByCamera[c.id]
                const edge = edgeStatusForCamera(c, edgeByCamera)
                const running = Boolean(edge?.running)
                const health = cameraHealth(c, edge)
                const summary = summaries[c.id]
                const busy = busyCamera === c.id
                return (
                  <div
                    key={c.id}
                    className="group flex flex-col rounded-xl border border-gray-200 bg-surface-200 shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-brand-500/40 hover:shadow-md"
                  >
                    <Link
                      to={`/app/cameras/${c.id}`}
                      className="flex flex-1 flex-col p-4"
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

                    <div className="flex items-center gap-1.5 border-t border-gray-100 px-3 py-2">
                      <Button
                        kind="secondary"
                        className="px-2.5 py-1.5 text-xs"
                        disabled={busy}
                        onClick={() => toggleRunning(c, running)}
                        aria-label={running ? `Stop ${c.name}` : `Start ${c.name}`}
                      >
                        {running ? 'Stop' : 'Start'}
                      </Button>
                      <Button
                        kind="ghost"
                        className="px-2.5 py-1.5 text-xs"
                        onClick={() => openEdit(c)}
                        aria-label={`Edit ${c.name}`}
                      >
                        Edit
                      </Button>
                      <Button
                        kind="ghost"
                        className="ml-auto px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50"
                        disabled={busy}
                        onClick={() => deleteCamera(c)}
                        aria-label={`Delete ${c.name}`}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      )}

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? `Edit “${editing.name}”` : 'Add camera'}
      >
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Name</span>
            <input
              className={inputCls}
              value={form.name}
              aria-label="Camera name"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Entrance Cam"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Location</span>
            <input
              className={inputCls}
              value={form.location}
              aria-label="Camera location"
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              placeholder="e.g. Front entrance"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Source type</span>
            <select
              className={inputCls}
              value={form.cameraType}
              aria-label="Camera source type"
              onChange={(e) => setForm({ ...form, cameraType: e.target.value })}
            >
              <option value="usb">USB / built-in webcam</option>
              <option value="file">Video file (test / demo)</option>
              <option value="rtsp">RTSP (reserved — not yet supported)</option>
            </select>
          </label>
          {form.cameraType === 'usb' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">
                Device index (0 = first webcam)
              </span>
              <input
                className={inputCls}
                type="number"
                min="0"
                value={form.sourceIndex}
                aria-label="Camera device index"
                onChange={(e) => setForm({ ...form, sourceIndex: e.target.value })}
              />
            </label>
          ) : (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">
                {form.cameraType === 'file' ? 'Video file path' : 'RTSP URL'}
              </span>
              <input
                className={inputCls}
                value={form.source}
                aria-label="Camera source"
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                placeholder={form.cameraType === 'file' ? '/path/to/video.mp4' : 'rtsp://…'}
              />
            </label>
          )}
          <div className="flex flex-wrap gap-4 pt-1">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.isActive}
                aria-label="Camera active"
                onChange={(e) => setForm({ ...form, isActive: e.target.checked })}
              />
              Active
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.personDetection}
                aria-label="Person detection"
                onChange={(e) => setForm({ ...form, personDetection: e.target.checked })}
              />
              People detection
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.productDetection}
                aria-label="Product detection"
                onChange={(e) => setForm({ ...form, productDetection: e.target.checked })}
              />
              Product detection
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.ocr}
                aria-label="Read product labels (OCR)"
                onChange={(e) => setForm({ ...form, ocr: e.target.checked })}
              />
              Read product labels (OCR)
            </label>
          </div>
          <p className="text-xs text-gray-400">
            OCR periodically reads a package held up to the camera (name, MFG/EXP dates, MRP) and
            matches the name to your catalog. It is assistive only — it never changes stock.
          </p>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Product detector</span>
            <select
              className={inputCls}
              aria-label="Product detector"
              value={form.productDetector}
              onChange={(e) => setForm({ ...form, productDetector: e.target.value })}
            >
              <option value="world">Open-vocabulary (YOLO-World) — your products</option>
              <option value="shelf">Fine-tuned FMCG model (legacy 55 classes)</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">
              Product prompts (optional)
            </span>
            <textarea
              className={inputCls}
              rows={3}
              aria-label="Product prompts"
              placeholder="biscuit packet, milk carton, soap bar"
              value={form.productPrompts}
              onChange={(e) => setForm({ ...form, productPrompts: e.target.value })}
            />
            <span className="mt-1 block text-xs text-gray-400">
              Comma- or line-separated. Leave blank to use your catalog automatically. The
              open-vocabulary detector only finds what these describe — never invented items.
            </span>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">
              AI processing FPS cap
            </span>
            <input
              type="number"
              min={0}
              step={1}
              className={inputCls}
              aria-label="AI processing FPS cap"
              value={form.fpsCap}
              onChange={(e) => setForm({ ...form, fpsCap: e.target.value })}
            />
            <span className="mt-1 block text-xs text-gray-400">
              0 = uncapped. Lower FPS lets one edge machine serve more cameras honestly.
            </span>
          </label>
          <p className="text-xs text-gray-400">
            A real camera needs a physical source. RTSP capture is reserved and will report an
            error until supported — no fake feed is ever substituted.
          </p>
          {formError ? <ErrorMessage error={formError} compact /> : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button kind="secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button kind="primary" onClick={saveCamera} disabled={saving || !form.name.trim()}>
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create camera'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

interface DemoCctvSectionProps {
  storeId: string | null
  onCameraCreated: (cameraId: string) => void
}

export function DemoCctvSection({ storeId, onCameraCreated }: DemoCctvSectionProps) {
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)
  const [statusMsg, setStatusMsg] = useState<{
    tone: 'green' | 'red'
    text: string
    camId?: string
  } | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const handleFile = (f: File) => {
    if (f.type.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm|m4v)$/i.test(f.name)) {
      setFile(f)
      setStatusMsg(null)
    } else {
      setStatusMsg({
        tone: 'red',
        text: 'Please select a valid video file (.mp4, .mov, .avi, .mkv, .webm)',
      })
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0])
    }
  }

  const uploadAndStart = async (selectedFile: File) => {
    if (!storeId) return
    setLoading(true)
    setStatusMsg(null)
    try {
      const res = await edgeApi.uploadDemoVideo(selectedFile, storeId)
      setStatusMsg({
        tone: 'green',
        text: `Demo camera "${res.name}" started! Video loops continuously with ByteTrack, YOLO-World, and shelf monitoring.`,
        camId: res.camera_id,
      })
      setFile(null)
      onCameraCreated(res.camera_id)
    } catch (err: unknown) {
      setStatusMsg({
        tone: 'red',
        text: err instanceof Error ? err.message : 'Could not upload or start video detection.',
      })
    } finally {
      setLoading(false)
    }
  }

  const loadSample = async (sampleKey: 'people' | 'shelf') => {
    if (!storeId) return
    setLoading(true)
    setStatusMsg(null)
    try {
      const res = await edgeApi.demoSample(sampleKey, storeId)
      setStatusMsg({
        tone: 'green',
        text: `Sample camera "${res.name}" started! Real store footage loops continuously with AI multi-detection.`,
        camId: res.camera_id,
      })
      onCameraCreated(res.camera_id)
    } catch (err: unknown) {
      setStatusMsg({
        tone: 'red',
        text: err instanceof Error ? err.message : 'Could not start sample video detection.',
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card p-5 border border-sky-200/80 bg-gradient-to-br from-white via-sky-50/20 to-surface-50 shadow-sm transition-all duration-200">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sky-100 text-sky-700">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </span>
            <h2 className="text-base font-bold text-gray-900">CCTV Detection Lab</h2>
            <Badge tone="green">Offline Edge AI</Badge>
          </div>
          <p className="mt-1 text-xs text-gray-600">
            Put any CCTV footage directly from Finder or test pre-loaded store footage. Real ByteTrack people tracking, open-vocabulary product detection, and shelf intelligence run locally with high FPS and zero frame drops.
          </p>
        </div>
      </div>

      {statusMsg && (
        <div
          className={`mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl p-3.5 text-xs font-medium ${
            statusMsg.tone === 'green'
              ? 'bg-emerald-50 border border-emerald-200 text-emerald-900'
              : 'bg-red-50 border border-red-200 text-red-900'
          }`}
        >
          <div className="flex items-center gap-2">
            <span>{statusMsg.tone === 'green' ? '✓' : '⚠️'}</span>
            <span>{statusMsg.text}</span>
          </div>
          {statusMsg.camId && (
            <Link
              to={`/app/cameras/${statusMsg.camId}`}
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700"
            >
              Watch Live Stream & Detections →
            </Link>
          )}
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Dropzone for Finder CCTV file */}
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`md:col-span-2 flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-all duration-150 ${
            dragOver
              ? 'border-brand-500 bg-brand-50/50 scale-[1.01]'
              : 'border-sky-300/80 bg-white hover:border-brand-400 hover:bg-sky-50/30'
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/*"
            className="hidden"
            aria-label="Upload CCTV footage"
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                handleFile(e.target.files[0])
              }
            }}
          />

          <svg className="h-8 w-8 text-sky-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className="mt-2 text-sm font-semibold text-gray-800">
            {file ? file.name : 'Drop CCTV video from Finder here'}
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            {file
              ? `${(file.size / (1024 * 1024)).toFixed(1)} MB · Click Start Detection below`
              : 'Or click to browse · Supports MP4, MOV, AVI, MKV, WebM (up to 200 MB)'}
          </p>

          {file && (
            <div className="mt-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              <Button
                kind="primary"
                onClick={() => uploadAndStart(file)}
                disabled={loading || !storeId}
              >
                {loading ? 'Starting Detector…' : 'Start Detection on This Clip'}
              </Button>
              <Button
                kind="secondary"
                onClick={() => setFile(null)}
                disabled={loading}
              >
                Clear
              </Button>
            </div>
          )}
        </div>

        {/* Pre-loaded sample footage */}
        <div className="flex flex-col justify-center space-y-2 rounded-xl border border-gray-200/80 bg-white p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Or Test Built-In Footage
          </p>
          <p className="text-xs text-gray-500">
            Instantly test without choosing a file from your computer:
          </p>
          <button
            type="button"
            onClick={() => loadSample('people')}
            disabled={loading || !storeId}
            className="flex items-center justify-between gap-2 rounded-lg border border-sky-100 bg-sky-50/60 px-3 py-2.5 text-left text-xs font-medium text-sky-900 transition hover:bg-sky-100/70 active:scale-[0.98] disabled:opacity-50"
          >
            <span className="flex items-center gap-2">
              <span className="text-sm">🚶</span>
              <span>Customer Flow (Entrance)</span>
            </span>
            <span className="text-[10px] font-bold text-sky-600">30 FPS</span>
          </button>
          <button
            type="button"
            onClick={() => loadSample('shelf')}
            disabled={loading || !storeId}
            className="flex items-center justify-between gap-2 rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2.5 text-left text-xs font-medium text-amber-900 transition hover:bg-amber-100/70 active:scale-[0.98] disabled:opacity-50"
          >
            <span className="flex items-center gap-2">
              <span className="text-sm">🥫</span>
              <span>Store Shelves & Products</span>
            </span>
            <span className="text-[10px] font-bold text-amber-600">30 FPS</span>
          </button>
        </div>
      </div>
    </div>
  )
}
