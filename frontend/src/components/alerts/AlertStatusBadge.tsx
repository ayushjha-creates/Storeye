// M16: Lifecycle status badge for alert cards. Mirrors the domain lifecycle
// (OPEN -> ACKNOWLEDGED -> RESOLVED, or -> DISMISSED; terminal states read-only).

import { Badge } from '../ui/Badge'
import type { AlertStatus } from '../../lib/api/types'

function statusTone(status: AlertStatus): 'gray' | 'green' | 'amber' {
  switch (status) {
    case 'OPEN':
      return 'amber'
    case 'ACKNOWLEDGED':
      return 'gray'
    default:
      return 'green' // RESOLVED / DISMISSED — terminal, read-only
  }
}

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  return (
    <Badge tone={statusTone(status)}>{status}</Badge>
  )
}