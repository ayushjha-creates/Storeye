// M20: Insight badges. Severity = business impact (never derived from AI
// confidence). Certainty = evidence strength behind the rule. Status = the
// lifecycle stage (OPEN / ACKNOWLEDGED / RESOLVED / EXPIRED).

import { Badge } from '../ui/Badge'
import type { BadgeTone } from '../ui/Badge'
import type { AlertSeverity, InsightCertainty, InsightStatus } from '../../lib/api/types'

function severityTone(severity: AlertSeverity): BadgeTone {
  switch (severity) {
    case 'CRITICAL':
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

export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  return <Badge tone={severityTone(severity)}>{severity}</Badge>
}

function statusTone(status: InsightStatus): BadgeTone {
  switch (status) {
    case 'OPEN':
      return 'red'
    case 'ACKNOWLEDGED':
      return 'amber'
    case 'RESOLVED':
      return 'green'
    default:
      return 'gray'
  }
}

export function StatusBadge({ status }: { status: InsightStatus }) {
  return <Badge tone={statusTone(status)}>{status}</Badge>
}

export function CertaintyBadge({ certainty }: { certainty: InsightCertainty }) {
  const tone: BadgeTone =
    certainty === 'HIGH' ? 'green' : certainty === 'MEDIUM' ? 'amber' : 'blue'
  return <Badge tone={tone}>{certainty}</Badge>
}