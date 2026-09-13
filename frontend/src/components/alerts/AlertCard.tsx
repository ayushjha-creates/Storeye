// M16: A single alert card. Shows type/severity/status/title/message, the
// product/shelf/camera context, evidence strength (confidence), detection time,
// and lifecycle actions. Actions are domain lifecycle transitions only — an
// alert can never edit inventory from here.

import { AlertSeverityBadge } from './AlertSeverityBadge'
import { AlertStatusBadge } from './AlertStatusBadge'
import { ALERT_TYPE_LABEL } from '../../lib/api/alerts'
import type { Alert } from '../../lib/api/types'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export function AlertCard({
  alert,
  onAction,
  onOpen,
}: {
  alert: Alert
  onAction: (alert: Alert, action: 'acknowledge' | 'resolve' | 'dismiss') => void
  onOpen: (alert: Alert) => void
}) {
  const terminal = alert.status === 'RESOLVED' || alert.status === 'DISMISSED'
  const actions: { action: 'acknowledge' | 'resolve' | 'dismiss'; label: string }[] = []
  if (alert.status === 'OPEN') {
    actions.push(
      { action: 'acknowledge', label: 'Acknowledge' },
      { action: 'resolve', label: 'Resolve' },
      { action: 'dismiss', label: 'Dismiss' },
    )
  } else if (alert.status === 'ACKNOWLEDGED') {
    actions.push(
      { action: 'resolve', label: 'Resolve' },
      { action: 'dismiss', label: 'Dismiss' },
    )
  }

  return (
    <article className="rounded-xl border border-gray-200 bg-surface-200 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-brand-700">
            {ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type}
          </span>
          <AlertSeverityBadge severity={alert.severity} />
          <AlertStatusBadge status={alert.status} />
        </div>
        <button
          onClick={() => onOpen(alert)}
          className="shrink-0 text-xs font-medium text-brand-700 hover:underline"
        >
          Evidence →
        </button>
      </div>

      <h3 className="mt-2 text-sm font-semibold text-gray-900">{alert.title}</h3>
      {alert.message ? <p className="mt-1 text-sm text-gray-600">{alert.message}</p> : null}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        {alert.product_id ? <span>Linked to a product</span> : null}
        {alert.camera_id ? <span>Linked to a camera</span> : null}
        {alert.shelf_id ? <span>Linked to a shelf</span> : null}
        {alert.confidence != null ? (
          <span>Confidence {Math.round(alert.confidence * 100)}%</span>
        ) : null}
        <span>Detected {formatTime(alert.last_detected_at)}</span>
      </div>

      {!terminal && actions.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map(({ action, label }) => (
            <button
              key={action}
              onClick={() => onAction(alert, action)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900"
            >
              {label}
            </button>
          ))}
          <span className="self-center text-[11px] text-gray-400">
            Informational — never auto-adjusts inventory.
          </span>
        </div>
      ) : (
        <p className="mt-3 text-[11px] text-gray-400">
          Terminal alert (read-only).
          {alert.status === 'RESOLVED' && alert.resolved_at
            ? ` Resolved ${formatTime(alert.resolved_at)}.`
            : alert.status === 'DISMISSED' && alert.dismissed_at
              ? ` Dismissed ${formatTime(alert.dismissed_at)}.`
              : ''}
        </p>
      )}
    </article>
  )
}