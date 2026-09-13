import { useCallback, useEffect, useState } from 'react'
import { useEdge } from '../edge/EdgeContext'
import { StatusPill } from './ui/Badge'
import { edgeApi } from '../lib/api/edge'
import type { EdgeStatus as EdgeRuntimeInfo } from '../lib/api/types'

/**
 * Edge System status panel.
 *
 * Emphasizes the edge-first operating model:
 *   EDGE ONLINE + INTERNET OFFLINE = NORMAL OPERATION ("Edge Mode")
 * The dashboard must never look "broken" just because the internet is down.
 *
 * AI runtime figures (active cameras, observations written, models loaded)
 * come from GET /api/edge/status — real counters, or "—" when unreachable.
 */
export function EdgeNodeStatus({ compact = false }: { compact?: boolean }) {
  const { status, refresh } = useEdge()
  const [runtime, setRuntime] = useState<EdgeRuntimeInfo | null | undefined>(undefined)

  const refreshRuntime = useCallback(async () => {
    try {
      setRuntime(await edgeApi.status())
    } catch {
      setRuntime(null)
    }
  }, [])

  useEffect(() => {
    refreshRuntime()
  }, [refreshRuntime])

  const Row = ({
    label,
    ok,
    statusText,
    value,
  }: {
    label: string
    ok?: boolean
    statusText?: string
    value?: string | null
  }) => (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-gray-500">{label}</span>
      {ok != null && statusText != null ? (
        <StatusPill ok={ok} label={statusText} />
      ) : (
        <span className="text-xs font-medium text-gray-700">{value ?? '—'}</span>
      )}
    </div>
  )

  if (compact) {
    return (
      <div className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            status.edgeOnline ? 'bg-emerald-500 shadow-[0_0_6px_1px_rgb(16_185_129/0.45)]' : 'bg-red-500'
          }`}
          aria-hidden="true"
        />
        <span className="text-xs font-medium text-gray-700">
          {status.edgeOnline ? 'EDGE ONLINE' : 'EDGE OFFLINE'}
        </span>
        {!status.internetOnline && (
          <span className="rounded bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
            INTERNET OFFLINE — NORMAL
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="card overflow-hidden">
      <header className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              status.edgeOnline ? 'bg-emerald-500' : 'bg-red-500'
            }`}
            aria-hidden="true"
          />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-800">
            Edge Node
          </h2>
        </div>
        <button
          onClick={() => {
            refresh()
            refreshRuntime()
          }}
          className="text-xs font-medium text-brand-700 hover:text-brand-800"
        >
          Refresh
        </button>
      </header>
      <div className="px-4 py-2">
        <Row
          label="Edge Node"
          ok={status.edgeOnline}
          statusText={status.edgeOnline ? 'ONLINE' : 'OFFLINE'}
        />
        <Row
          label="AI Runtime"
          ok={runtime ? !runtime.offline : status.edgeOnline}
          statusText={
            runtime ? (runtime.offline ? 'STOPPED' : 'RUNNING') : status.edgeOnline ? 'CHECKING' : 'UNKNOWN'
          }
        />
        <Row
          label="Active cameras"
          value={runtime ? `${runtime.active_cameras}/${runtime.camera_count}` : null}
        />
        <Row
          label="Observations written"
          value={runtime?.observations_written != null ? String(runtime.observations_written) : null}
        />
        <Row
          label="Models loaded"
          value={
            runtime && runtime.models_loaded.length > 0 ? runtime.models_loaded.join(', ') : null
          }
        />
        <Row
          label="PostgreSQL"
          ok={status.edgeOnline}
          statusText={status.stores != null ? 'CONNECTED' : 'UNKNOWN'}
        />
        <Row
          label="FastAPI"
          ok={status.edgeOnline}
          statusText={status.edgeOnline ? 'CONNECTED' : 'UNREACHABLE'}
        />
        <Row
          label="Internet"
          ok={status.internetOnline}
          statusText={status.internetOnline ? 'ONLINE' : 'OFFLINE'}
        />
      </div>
      {!status.internetOnline && status.edgeOnline && (
        <div className="border-t border-gray-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-700">
          <span className="font-semibold uppercase tracking-wide">Edge Mode</span> — cameras, AI
          and PostgreSQL all run on this local node; internet is never required. This is normal
          operation.
        </div>
      )}
      <p className="border-t border-gray-100 px-4 py-2 text-[11px] text-gray-400">
        {status.lastCheckedAt
          ? `Last checked ${new Date(status.lastCheckedAt).toLocaleTimeString()}`
          : 'Checking…'}
      </p>
    </div>
  )
}