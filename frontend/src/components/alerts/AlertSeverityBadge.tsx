// M16: Severity badge for alerts. Severity = business impact; it is a separate
// concept from AI confidence (evidence strength) and is never derived from it.

import { Badge } from '../ui/Badge'
import type { AlertSeverity } from '../../lib/api/types'
import { ALERT_SEVERITY_LABEL } from '../../lib/shop'

function severityTone(severity: AlertSeverity): 'gray' | 'green' | 'amber' | 'red' | 'blue' {
  switch (severity) {
    case 'CRITICAL':
      return 'red'
    case 'HIGH':
      return 'red'
    case 'MEDIUM':
      return 'amber'
    case 'LOW':
      return 'blue'
    default:
      return 'gray'
  }
}

export function AlertSeverityBadge({ severity }: { severity: AlertSeverity }) {
  return (
    <Badge tone={severityTone(severity)}>
      {ALERT_SEVERITY_LABEL[severity]}
    </Badge>
  )
}

export function severityToneFor(severity: AlertSeverity) {
  return severityTone(severity)
}