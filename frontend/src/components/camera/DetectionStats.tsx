import { Badge } from '../ui/Badge'
import type {
  ActivityBucket,
  Camera,
  EdgeCameraStatus,
  ObservationSummary,
} from '../../lib/api/types'

// Detection Statistics + AI Runtime Performance panel.
//
// HARD RULE: every number is real. Values come from GET /api/observations/summary
// (aggregated over the last 24h of stored observations) and GET /api/edge/cameras
// (live Edge runtime counters). When the runtime or summary is unavailable we say
// so explicitly ("Not available") — we NEVER substitute fake statistics.

interface DetectionStatsProps {
  camera: Camera
  edge: EdgeCameraStatus | null
  summary: ObservationSummary | null
}

function ActivityChart({ activity }: { activity: ActivityBucket[] }) {
  const max = Math.max(1, ...activity.map((b) => b.count))
  return (
    <div className="mt-2 rounded-lg border border-gray-100 bg-gray-50/60 p-2.5">
      <div className="flex h-16 items-end gap-1">
        {activity.map((b) => (
          <div
            key={b.bucket_ts}
            className="flex-1 rounded-t-sm bg-brand-300 transition-all duration-150 hover:bg-brand-500"
            style={{ height: `${Math.max(6, Math.round((b.count / max) * 100))}%` }}
            title={`${new Date(b.bucket_ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} — ${b.count} detection(s)`}
          />
        ))}
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] font-medium text-gray-400">
        <span>24h ago</span>
        <span>Now</span>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'positive' | 'warning' | 'default' }) {
  const color =
    tone === 'positive' ? 'text-emerald-700' : tone === 'warning' ? 'text-amber-700' : 'text-gray-900'
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`mt-0.5 text-xl font-bold ${color}`}>{value}</p>
    </div>
  )
}

// Canonical backend health enum -> badge (single source of truth).
const HEALTH_BADGE: Record<string, { tone: 'green' | 'amber' | 'red' | 'gray'; label: string }> = {
  RUNNING: { tone: 'green', label: 'RUNNING' },
  DEGRADED: { tone: 'amber', label: 'DEGRADED' },
  STARTING: { tone: 'amber', label: 'CONNECTING' },
  ERROR: { tone: 'red', label: 'ERROR' },
  STOPPED: { tone: 'gray', label: 'STOPPED' },
  DISABLED: { tone: 'gray', label: 'DISABLED' },
}

export function DetectionStats({ camera, edge, summary }: DetectionStatsProps) {
  const byType = summary?.by_type ?? {}
  const people = byType.PERSON ?? 0
  const products = byType.PRODUCT ?? 0
  const textObs = byType.TEXT ?? 0
  const expiryObs = byType.EXPIRY_METADATA ?? 0
  const activity = Array.isArray(summary?.activity) ? summary.activity : []
  const cfg = (camera.config ?? {}) as Record<string, unknown>
  const cfgPipelines = (cfg.pipelines ?? {}) as Record<string, unknown>
  const productDetectionEnabled =
    edge?.enabled_pipelines?.product_detection ??
    ((cfgPipelines.product_detection ?? cfg.product_detection) !== false)

  const dropPct =
    edge && edge.frames_captured > 0
      ? Math.round((edge.frames_dropped / edge.frames_captured) * 100)
      : null

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-gray-200 bg-surface-200 shadow-sm">
        <header className="border-b border-gray-100 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            Detection statistics
          </p>
          <p className="mt-0.5 text-sm font-semibold text-gray-900">Last 24 hours (real data)</p>
        </header>
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
          <Stat label="Detections" value={summary ? summary.total : '—'} />
          <Stat label="People" value={summary ? people : '—'} />
          <Stat label="Products" value={summary ? products : '—'} />
          <Stat label="OCR events" value={summary ? textObs : '—'} />
        </div>
        <div className="grid grid-cols-2 gap-3 px-4 pb-4 sm:grid-cols-4">
          <Stat
            label="Avg confidence"
            value={summary?.avg_confidence != null ? `${Math.round(summary.avg_confidence * 100)}%` : '—'}
          />
          <Stat label="Tracked people" value={summary ? summary.distinct_tracks : '—'} />
          <Stat label="Expiry info" value={summary ? expiryObs : '—'} />
          <Stat
            label="Last seen"
            value={summary?.last_observed_at ? new Date(summary.last_observed_at).toLocaleTimeString() : '—'}
          />
        </div>

        <div className="border-t border-gray-100 px-4 py-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-500">Detection activity over time</p>
            <p className="text-[11px] text-gray-400">
              {activity.length > 0 ? `${activity.length} bucket(s) · UTC` : 'no data'}
            </p>
          </div>
          {activity.length > 0 ? (
            <ActivityChart activity={activity} />
          ) : (
            <p className="mt-2 text-sm text-gray-400">No detections in the last 24 hours.</p>
          )}
        </div>

        {!productDetectionEnabled && (
          <p className="border-t border-gray-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            Product detection is not enabled for this camera — product counters stay at 0 until it
            is turned on in the camera config.
          </p>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 bg-surface-200 shadow-sm">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              AI runtime performance
            </p>
            <p className="mt-0.5 text-sm font-semibold text-gray-900">Local Edge runtime</p>
          </div>
          {edge ? (
            <Badge tone={HEALTH_BADGE[edge.health]?.tone ?? 'gray'}>
              {HEALTH_BADGE[edge.health]?.label ?? edge.health}
            </Badge>
          ) : (
            <Badge tone="gray">UNKNOWN</Badge>
          )}
        </header>

        {!edge ? (
          <p className="px-4 py-4 text-sm text-gray-500">
            AI runtime status not available — is the Edge Runtime running and is this camera
            configured in it?
          </p>
        ) : (
          <>
            {edge.error ? (
              <p className="border-b border-gray-200 bg-red-50 px-4 py-2 text-xs text-red-600">
                {edge.error}
              </p>
            ) : null}
            <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
              <Stat
                label="Capture FPS"
                value={
                  edge.frames_captured === 0
                    ? 'Measuring…'
                    : (edge.capture_fps ?? edge.fps ?? 0).toFixed(1)
                }
                tone={(edge.capture_fps ?? edge.fps ?? 0) > 0 ? 'positive' : 'default'}
              />
              <Stat
                label="Inference FPS"
                value={
                  edge.frames_processed === 0
                    ? 'Measuring…'
                    : (edge.inference_fps ?? edge.fps ?? 0).toFixed(1)
                }
                tone={(edge.inference_fps ?? edge.fps ?? 0) > 0 ? 'positive' : 'default'}
              />
              <Stat label="Frames captured" value={edge.frames_captured} />
              <Stat label="Frames processed" value={edge.frames_processed} />
            </div>
            <div className="grid grid-cols-2 gap-3 px-4 pb-4 sm:grid-cols-4">
              <Stat label="Drop rate" value={dropPct != null ? `${dropPct}%` : '—'} />
              <Stat label="Frames dropped" value={edge.frames_dropped} />
              <Stat
                label="Inference latency"
                value={edge.inference_ms != null ? `${edge.inference_ms.toFixed(0)} ms` : 'Measuring…'}
              />
              <Stat label="Observations written" value={edge.observations_written} />
            </div>
            <div className="grid grid-cols-2 gap-3 px-4 pb-4 sm:grid-cols-4">
              <Stat
                label="AI target FPS"
                value={(edge.ai_target_fps ?? 0) > 0 ? String(edge.ai_target_fps) : 'Uncapped'}
              />
              <Stat
                label="Re-ID runs / skips"
                value={
                  edge.person_cache
                    ? `${edge.person_cache.reid_invocations} / ${edge.person_cache.reid_skipped}`
                    : 'n/a'
                }
              />
              <Stat
                label="Cache hit rate"
                value={
                  edge.person_cache && edge.person_cache.hits + edge.person_cache.misses > 0
                    ? `${Math.round(
                        (edge.person_cache.hits /
                          (edge.person_cache.hits + edge.person_cache.misses)) *
                          100,
                      )}%`
                    : 'Measuring…'
                }
              />
              <Stat
                label="Uptime"
                value={
                  edge.uptime_seconds
                    ? `${Math.round(edge.uptime_seconds / 60)}m ${edge.uptime_seconds % 60}s`
                    : 'Not available'
                }
              />
            </div>
            {edge.stage_profile && Object.keys(edge.stage_profile).length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
                <span className="font-medium">Stage latency (p50):</span>
                {Object.entries(edge.stage_profile).map(([key, s]) => (
                  <span key={key} className="rounded bg-gray-100 px-2 py-0.5">
                    {key} ≈ {Number(s.p50_ms).toFixed(0)} ms
                  </span>
                ))}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
              <span className="font-medium">Pipelines:</span>
              {edge.enabled_pipelines ? (
                <>
                  <Badge tone={edge.enabled_pipelines.person_detection ? 'green' : 'gray'}>
                    Person {edge.enabled_pipelines.person_detection ? 'ON' : 'OFF'}
                  </Badge>
                  <Badge tone={edge.enabled_pipelines.product_detection ? 'green' : 'gray'}>
                    Product {edge.enabled_pipelines.product_detection ? 'ON' : 'OFF'}
                  </Badge>
                  <Badge tone={edge.enabled_pipelines.ocr ? 'green' : 'gray'}>
                    OCR {edge.enabled_pipelines.ocr ? 'ON' : 'OFF'}
                  </Badge>
                </>
              ) : (
                <span className="text-gray-400">unknown</span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}