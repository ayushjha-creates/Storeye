// M16: Alert evidence detail. Shows the persisted `details` evidence blob plus
// provenance. Evidence is metadata/JSONB only — raw video or frames are NEVER
// stored by Storeye, and this panel never mutates anything.

import { Modal } from '../ui/Modal'
import { AlertSeverityBadge } from './AlertSeverityBadge'
import { AlertStatusBadge } from './AlertStatusBadge'
import { ALERT_TYPE_LABEL } from '../../lib/api/alerts'
import type { Alert } from '../../lib/api/types'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export function AlertDetail({
  alert,
  onClose,
}: {
  alert: Alert
  onClose: () => void
}) {
  const entries = alert.details
    ? Object.entries(alert.details).filter(([, v]) => v !== null && v !== undefined)
    : []

  return (
    <Modal
      open
      onClose={onClose}
      title={`${ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type} alert`}
      wide
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <AlertSeverityBadge severity={alert.severity} />
          <AlertStatusBadge status={alert.status} />
          {alert.confidence != null ? (
            <span className="text-xs text-gray-500">
              Confidence {Math.round(alert.confidence * 100)}% (evidence strength)
            </span>
          ) : null}
        </div>

        <div>
          <h3 className="text-sm font-semibold text-gray-900">{alert.title}</h3>
          {alert.message ? <p className="mt-1 text-sm text-gray-600">{alert.message}</p> : null}
        </div>

        <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">First detected</dt>
            <dd className="font-medium text-gray-700">{formatTime(alert.first_detected_at)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Last detected</dt>
            <dd className="font-medium text-gray-700">{formatTime(alert.last_detected_at)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Source</dt>
            <dd className="font-medium text-gray-700">{alert.source_type ?? '—'}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Source ID</dt>
            <dd className="max-w-[220px] truncate font-mono text-gray-700" title={alert.source_id ?? undefined}>
              {alert.source_id ?? '—'}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Product</dt>
            <dd className="max-w-[220px] truncate font-medium text-gray-700">
              {alert.product_id ?? '—'}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Camera</dt>
            <dd className="max-w-[220px] truncate font-medium text-gray-700">
              {alert.camera_id ?? '—'}
            </dd>
          </div>
        </dl>

        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Evidence details (metadata only)
          </p>
          {entries.length === 0 ? (
            <p className="text-sm text-gray-500">No additional evidence captured.</p>
          ) : (
            <table className="w-full table-fixed text-left text-xs">
              <tbody className="divide-y divide-gray-100">
                {entries.map(([key, value]) => (
                  <tr key={key}>
                    <td className="w-2/5 py-1.5 pr-2 font-medium text-gray-500">{key}</td>
                    <td className="break-words py-1.5 font-mono text-gray-800">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <p className="text-[11px] text-gray-400">
          Alerts are informational/actionable. Storeye never auto-adjusts inventory from an
          alert — stock changes remain explicit, human-reviewed operations.
        </p>
      </div>
    </Modal>
  )
}