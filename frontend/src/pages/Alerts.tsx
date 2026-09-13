// M16: Storeye Alerts — actionable intelligence centre.
//
// Reads the alert list (filterable), applies rules via "Evaluate now" (which
// only reasons over EXISTING intelligence — no camera inference, no network,
// and no inventory mutation), and drives the lifecycle (acknowledge / resolve /
// dismiss). Everything is local and offline-first.

import { useCallback, useEffect, useState } from 'react'
import { Card, Stat } from '../components/ui/Card'
import { Button } from '../components/ui/Modal'
import { ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { AlertFilters } from '../components/alerts/AlertFilters'
import { AlertList } from '../components/alerts/AlertList'
import { AlertDetail } from '../components/alerts/AlertDetail'
import { alertApi } from '../lib/api/alerts'
import { storeApi } from '../lib/api/zone'
import type { Alert, AlertType, AlertSeverity, AlertStatus } from '../lib/api/types'

export function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [alertType, setAlertType] = useState<AlertType | ''>('')
  const [severity, setSeverity] = useState<AlertSeverity | ''>('')
  const [status, setStatus] = useState<AlertStatus | ''>('')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        sid = stores.items[0]?.id ?? null
      } catch {
        sid = null
      }
      if (!sid) {
        setAlerts([])
        return
      }
      const res = await alertApi.list({
        store_id: sid,
        alert_type: alertType || null,
        severity: severity || null,
        status: status || null,
        limit: 100,
      })
      setAlerts(res.items)
    } catch (err) {
      setError(err)
      setAlerts([])
    } finally {
      setLoading(false)
    }
  }, [alertType, severity, status])

  useEffect(() => {
    load()
  }, [load])

  const runEvaluate = async () => {
    setEvaluating(true)
    setError(null)
    try {
      const stores = await storeApi.list()
      const sid = stores.items[0]?.id
      if (!sid) return
      await alertApi.evaluate({ store_id: sid, hours: 24 })
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setEvaluating(false)
    }
  }

  const runAction = async (alert: Alert, action: 'acknowledge' | 'resolve' | 'dismiss') => {
    try {
      const updated =
        action === 'acknowledge'
          ? await alertApi.acknowledge(alert.id)
          : action === 'resolve'
            ? await alertApi.resolve(alert.id)
            : await alertApi.dismiss(alert.id)
      setAlerts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
      if (selected?.id === updated.id) setSelected(updated)
    } catch (err) {
      setError(err)
    }
  }

  const openCount = alerts.filter((a) => a.status === 'OPEN').length
  const highCritical = alerts.filter(
    (a) => a.severity === 'HIGH' || a.severity === 'CRITICAL',
  ).length

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-bold">Alerts</h1>
          </div>
          <p className="mt-0.5 text-sm text-black">
            Actionable intelligence derived from existing AI results.{' '}
            <span className="font-medium">Informational only</span> — alerts never change
            stock; they ask a human to review.
          </p>
        </div>
        <Button kind="secondary" onClick={runEvaluate} disabled={evaluating || loading}>
          {evaluating ? 'Evaluating…' : 'Evaluate now'}
        </Button>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading alerts…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Alerts" value={alerts.length} hint="current filter" />
            <Stat label="Open" value={openCount} tone={openCount ? 'warning' : 'positive'} />
            <Stat
              label="High / Critical"
              value={highCritical}
              tone={highCritical ? 'danger' : 'default'}
              hint="business impact severity"
            />
            <Stat
              label="Evaluating"
              value="Now"
              hint="applies rules over existing intelligence"
            />
          </div>

          <Card
            title="Alert inbox"
            subtitle="Filter, acknowledge, resolve or dismiss. Evidence panel shows the persisted details."
          >
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <AlertFilters
                alertType={alertType}
                severity={severity}
                status={status}
                onChange={(patch) => {
                  if (patch.alertType !== undefined) setAlertType(patch.alertType)
                  if (patch.severity !== undefined) setSeverity(patch.severity)
                  if (patch.status !== undefined) setStatus(patch.status)
                }}
              />
            </div>

            <AlertList alerts={alerts} onAction={runAction} onOpen={setSelected} />
          </Card>
        </>
      )}

      {selected ? <AlertDetail alert={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  )
}