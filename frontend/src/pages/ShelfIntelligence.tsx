import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Stat } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { intelligenceApi, SHELF_STATE_LABEL } from '../lib/api/intelligence'
import { alertApi, ALERT_TYPE_LABEL } from '../lib/api/alerts'
import { storeApi } from '../lib/api/zone'
import { IconShelf } from '../components/ui/icons'
import type { AISummary, Alert, ShelfIntelligenceRow } from '../lib/api/types'

function stateTone(status: string): 'gray' | 'green' | 'amber' | 'red' {
  switch (status) {
    case 'NORMAL_VISIBLE':
      return 'green'
    case 'LOW_VISIBLE':
      return 'amber'
    case 'EMPTY_VISIBLE':
      return 'red'
    default:
      return 'gray'
  }
}

export function ShelfIntelligencePage() {
  const [rows, setRows] = useState<ShelfIntelligenceRow[]>([])
  const [summary, setSummary] = useState<AISummary | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
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
      if (sid) {
        const [shelves, ai] = await Promise.all([
          intelligenceApi.shelves({ store_id: sid }),
          intelligenceApi.summary({ store_id: sid }),
        ])
        setRows(shelves.items)
        setSummary(ai)

        try {
          const alertRes = await alertApi.list({ store_id: sid, status: 'OPEN', limit: 10 })
          setAlerts(alertRes.items)
        } catch {
          setAlerts([]) // related alerts are best effort
        }
      } else {
        setRows([])
        setSummary(null)
      }
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const shelfStats = useMemo(() => {
    const low = rows.filter((r) => r.detection_status === 'LOW_VISIBLE').length
    const empty = rows.filter((r) => r.detection_status === 'EMPTY_VISIBLE').length
    const ok = rows.filter((r) => r.detection_status === 'NORMAL_VISIBLE').length
    const unknown = rows.filter((r) => r.detection_status === 'UNKNOWN').length
    const misplaced = summary?.shelves.possible_misplacements ?? 0
    return { low, empty, ok, unknown, misplaced }
  }, [rows, summary])

  const relatedAlerts = useMemo(
    () =>
      alerts
        .filter(
          (a) =>
            a.alert_type === 'LOW_SHELF_OCCUPANCY' || a.alert_type === 'MISPLACEMENT',
        )
        .slice(0, 5),
    [alerts],
  )

  return (
    <div className="page-shell space-y-6">
      <div>
        <div className="flex items-center gap-2.5">
          <span className="rounded-lg bg-gray-100 p-1.5">
            <IconShelf className="h-4 w-4 text-brand-600" />
          </span>
          <h1 className="font-bold">Shelf Intelligence</h1>
        </div>
        <p className="text-sm text-black">
          AI-estimated visible occupancy per configured shelf region. This is{' '}
          <span className="font-medium">not stock</span> — it reflects what the camera
          currently sees.
        </p>
      </div>

      {error && !loading ? <ErrorMessage error={error} onRetry={load} /> : null}

      {relatedAlerts.length > 0 ? (
        <Link
          to="/app/alerts"
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm"
        >
          <div>
            <p className="font-medium text-amber-900">
              {relatedAlerts.length} related open alert{relatedAlerts.length === 1 ? '' : 's'}
            </p>
            <p className="text-xs text-amber-700">
              {relatedAlerts
                .slice(0, 3)
                .map((a) => `${ALERT_TYPE_LABEL[a.alert_type]} · ${a.title}`)
                .join(' · ')}
            </p>
          </div>
          <span className="font-medium text-brand-700">View in Alerts →</span>
        </Link>
      ) : null}

      {loading ? (
        <Spinner label="Loading shelf intelligence…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            <Stat label="Regions" value={rows.length} hint="Configured shelf_regions" />
            <Stat label="OK" value={shelfStats.ok} tone="positive" />
            <Stat label="Low" value={shelfStats.low} hint="Below 35% occupancy" tone={shelfStats.low ? 'warning' : 'default'} />
            <Stat label="Empty (visible)" value={shelfStats.empty} hint="No visible product" tone={shelfStats.empty ? 'danger' : 'default'} />
            <Stat label="Possible misplaced" value={shelfStats.misplaced} tone={shelfStats.misplaced ? 'warning' : 'default'} />
          </div>

          <Card
            title="Shelves"
            subtitle="Occupancy is an AI estimate (product bbox area within the region). ‘Unknown’ means the camera produced no AI data in the window."
          >
            {rows.length === 0 ? (
              <EmptyState
                title="No shelf regions configured"
                hint="Add shelf_regions to a camera's config (and run the Edge AI) to see shelf intelligence here."
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {rows.map((r, idx) => {
                  const occupancy =
                    r.estimated_visible_occupancy != null
                      ? `${Math.round(r.estimated_visible_occupancy * 100)}%`
                      : 'Unavailable'
                  return (
                    <div
                      key={`${r.shelf_code}-${r.camera_id ?? idx}`}
                      className="card p-4"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h3 className="text-sm font-semibold">
                            {r.region_label ?? `Shelf ${r.shelf_code}`}
                          </h3>
                          <p className="text-xs text-gray-500">
                            {r.shelf_code}
                            {r.zone_name ? ` · ${r.zone_name}` : ''} · {r.camera_name ?? 'camera'}
                          </p>
                        </div>
                        <Badge tone={stateTone(r.detection_status)}>
                          {SHELF_STATE_LABEL[r.detection_status] ?? r.detection_status}
                        </Badge>
                      </div>

                      <div className="mt-3">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">AI-estimated visible occupancy</span>
                          <span className="font-semibold text-gray-700">{occupancy}</span>
                        </div>
                        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-100">
                          <div
                            className="h-2 rounded-full bg-brand-600"
                            style={{
                              width: `${Math.min(100, (r.estimated_visible_occupancy ?? 0) * 100)}%`,
                            }}
                          />
                        </div>
                      </div>

                      {r.last_analysis_message ? (
                        <p className="mt-2 text-xs text-gray-400">{r.last_analysis_message}</p>
                      ) : null}

                      {r.visible_products.length > 0 ? (
                        <ul className="mt-3 space-y-1.5">
                          {r.visible_products.map((p) => (
                            <li
                              key={p.ai_class}
                              className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-1.5 text-sm"
                            >
                              <span className="flex items-center gap-2">
                                <span className="font-medium text-gray-800">{p.ai_class}</span>
                                {p.product_name ? (
                                  <span className="text-xs text-gray-500">
                                    → {p.product_name}
                                  </span>
                                ) : null}
                                {p.possible_misplacement ? (
                                  <Badge tone="amber">possible misplaced</Badge>
                                ) : null}
                              </span>
                              <span className="text-xs text-gray-500">×{p.visible_count}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-3 text-xs text-gray-400">No product detected here.</p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}