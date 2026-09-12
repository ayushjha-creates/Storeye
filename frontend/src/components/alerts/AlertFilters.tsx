// M16: Alert filter bar. All filters are read-only queries against the local
// backend — filtering never re-evaluates rules nor touches inventory.

import { ALERT_TYPE_ORDER, ALERT_SEVERITY_ORDER, ALERT_STATUS_ORDER } from '../../lib/api/alerts'
import type { AlertType, AlertSeverity, AlertStatus } from '../../lib/api/types'

export function AlertFilters({
  alertType,
  severity,
  status,
  alertTypeOptions = ALERT_TYPE_ORDER,
  disabled,
  onChange,
}: {
  alertType: AlertType | ''
  severity: AlertSeverity | ''
  status: AlertStatus | ''
  alertTypeOptions?: AlertType[]
  disabled?: boolean
  onChange: (patch: {
    alertType?: AlertType | ''
    severity?: AlertSeverity | ''
    status?: AlertStatus | ''
  }) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label="Filter by alert type"
        value={alertType}
        disabled={disabled}
        onChange={(e) => onChange({ alertType: e.target.value as AlertType | '' })}
        className="w-44 rounded-lg border border-white/[0.1] bg-white/[0.04] px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none disabled:text-gray-300"
      >
        <option value="">All alert types</option>
        {alertTypeOptions.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <select
        aria-label="Filter by severity"
        value={severity}
        disabled={disabled}
        onChange={(e) => onChange({ severity: e.target.value as AlertSeverity | '' })}
        className="w-32 rounded-lg border border-white/[0.1] bg-white/[0.04] px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none disabled:text-gray-300"
      >
        <option value="">All severities</option>
        {ALERT_SEVERITY_ORDER.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <select
        aria-label="Filter by status"
        value={status}
        disabled={disabled}
        onChange={(e) => onChange({ status: e.target.value as AlertStatus | '' })}
        className="w-36 rounded-lg border border-white/[0.1] bg-white/[0.04] px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none disabled:text-gray-300"
      >
        <option value="">All statuses</option>
        {ALERT_STATUS_ORDER.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  )
}