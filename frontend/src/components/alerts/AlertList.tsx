// M16: Alert list. Renders alert cards or an offline-friendly empty state.
// Alerts reflect persisted state — no re-evaluation happens on render.

import { AlertCard } from './AlertCard'
import { EmptyState } from '../ui/ErrorState'
import type { Alert } from '../../lib/api/types'

export function AlertList({
  alerts,
  onAction,
  onOpen,
}: {
  alerts: Alert[]
  onAction: (alert: Alert, action: 'acknowledge' | 'resolve' | 'dismiss') => void
  onOpen: (alert: Alert) => void
}) {
  if (alerts.length === 0) {
    return (
      <EmptyState
        title="Nothing flagged"
        hint="Run “Check now” after your cameras have been watching to review anything Storeye noticed."
      />
    )
  }
  return (
    <div className="space-y-3">
      {alerts.map((a) => (
        <AlertCard key={a.id} alert={a} onAction={onAction} onOpen={onOpen} />
      ))}
    </div>
  )
}