import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Stat } from '../components/ui/Card'
import { EmptyState, ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { Badge } from '../components/ui/Badge'
import { EdgeNodeStatus } from '../components/EdgeNodeStatus'
import { MiniProgress } from '../components/ui/charts'
import { useEdge } from '../edge/EdgeContext'
import { cleanName } from '../lib/cleanNames'
import { storeApi, zoneApi, shelfApi } from '../lib/api/zone'
import { cameraApi } from '../lib/api/cameras'
import { observationApi } from '../lib/api/observations'
import { intelligenceApi } from '../lib/api/intelligence'
import type {
  Camera,
  Observation,
  ProductIntelligenceRow,
  Shelf,
  ShelfIntelligenceRow,
  Store,
  Zone,
} from '../lib/api/types'
import { IconCamera, IconRefresh, IconStore, IconUsers } from '../components/ui/icons'

const REFRESH_MS = 30_000

function isSameDay(iso: string): boolean {
  const d = new Date(iso)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

const SHELF_STATE: Record<string, { label: string; tone: 'green' | 'amber' | 'red' | 'gray' | 'blue' }> = {
  EMPTY_VISIBLE: { label: 'Empty', tone: 'red' },
  LOW_VISIBLE: { label: 'Low', tone: 'amber' },
  NORMAL_VISIBLE: { label: 'OK', tone: 'green' },
  UNKNOWN: { label: 'No data', tone: 'gray' },
}

const COMPARISON_TONE: Record<string, 'green' | 'amber' | 'red' | 'purple' | 'gray'> = {
  MATCH: 'green',
  POSSIBLE_SHORTAGE: 'red',
  POSSIBLE_SURPLUS: 'amber',
  NO_INVENTORY: 'purple',
  NOT_ASSESSED: 'gray',
}

export function LiveStorePage() {
  const { edgeOnline } = useEdge().status
  const [store, setStore] = useState<Store | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [zones, setZones] = useState<Zone[]>([])
  const [shelves, setShelves] = useState<Shelf[]>([])
  const [obs, setObs] = useState<Observation[]>([])
  const [shelfIntel, setShelfIntel] = useState<ShelfIntelligenceRow[]>([])
  const [productIntel, setProductIntel] = useState<ProductIntelligenceRow[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        const first = stores.items[0]
        if (first) {
          sid = first.id
          setStore(first)
        }
      } catch {
        // store may be unreachable; continue for other reads
      }

      const [camRes, zoneRes, shelfRes, obsRes] = await Promise.all([
        cameraApi.list(sid ? { store_id: sid } : undefined),
        zoneApi.list(sid ? { store_id: sid } : undefined),
        shelfApi.list(sid ? { store_id: sid } : undefined),
        observationApi.list({ limit: 150 }),
      ])
      setCameras(camRes.items)
      setZones(zoneRes.items)
      setShelves(shelfRes.items)
      setObs(obsRes.items)

      if (sid) {
        const [shelfRow, productRow] = await Promise.all([
          intelligenceApi.shelves({ store_id: sid }).catch(() => null),
          intelligenceApi.products({ store_id: sid }).catch(() => null),
        ])
        setShelfIntel(shelfRow?.items ?? [])
        setProductIntel(productRow?.items ?? [])
      } else {
        setShelfIntel([])
        setProductIntel([])
      }
      setLastUpdated(new Date())
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(t)
  }, [load])

  const peopleToday = obs.filter((o) => o.observation_type === 'PERSON' && isSameDay(o.observed_at)).length
  const activeCameras = cameras.filter((c) => c.is_active).length
  const regionsWithData = shelfIntel.filter((s) => s.detection_status !== 'UNKNOWN').length
  const visibleUnits = productIntel.reduce((sum, p) => sum + p.visible_count, 0)
  const visibleProducts = productIntel.filter((p) => p.visible_count > 0).length

  const intelByCode = new Map(shelfIntel.map((s) => [s.shelf_code, s]))
  const zonesWithShelves = zones
    .map((z) => ({ zone: z, shelves: shelves.filter((s) => s.zone_id === z.id) }))
    .filter((g) => g.shelves.length > 0)

  const recentProductObs = obs
    .filter((o) => o.observation_type === 'PRODUCT')
    .slice()
    .sort((a, b) => b.observed_at.localeCompare(a.observed_at))
    .slice(0, 8)

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="font-bold">Live Store</h1>
          </div>
          <p className="mt-0.5 text-sm text-black">
            {store ? cleanName(store.name) : 'Loading store…'} ·{' '}
            {edgeOnline ? 'Streaming from the Edge AI runtime' : 'Showing last known good data'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && <span className="text-xs text-gray-400">Refreshed {lastUpdated.toLocaleTimeString()}</span>}
          <button
            onClick={load}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900"
          >
            <IconRefresh className="h-3.5 w-3.5" /> Refresh
          </button>
          <EdgeNodeStatus compact />
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading live store…" />
      ) : (
        <>
          {/* Live KPIs */}
          <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="People in store"
              value={peopleToday}
              hint="distinct tracks today"
              icon={<IconUsers className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Active cameras"
              value={
                <span className="inline-flex items-center gap-2">
                  {activeCameras}/{cameras.length}
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
                    <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
                    live
                  </span>
                </span>
              }
              hint="edge AI on premises"
              icon={<IconCamera className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Regions with AI data"
              value={
                <span>
                  {regionsWithData}
                  <span className="text-base font-semibold text-gray-500">/{shelfIntel.length}</span>
                </span>
              }
              hint="shelf regions analysed"
              icon={<IconStore className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Visible stock"
              value={visibleUnits}
              hint={`${visibleProducts} products visible`}
              icon={<IconCamera className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Storefront shelf map */}
            <Card
              className="xl:col-span-2"
              title="Storefront shelf map"
              subtitle="Occupancy derived from Edge AI detections — informational only"
              action={
                <Link to="/app/shelf-intelligence" className="text-xs font-medium text-brand-700 hover:underline">
                  Details →
                </Link>
              }
            >
              {shelves.length === 0 ? (
                <EmptyState
                  title="No shelving configured"
                  hint="Create shelf regions with the camera calibration so the Edge AI can map detections to shelves."
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {zonesWithShelves.length === 0 &&
                    shelves.map((s) => {
                      const intel = intelByCode.get(s.code)
                      const state = intel ? SHELF_STATE[intel.detection_status] ?? SHELF_STATE.UNKNOWN : SHELF_STATE.UNKNOWN
                      return (
                        <ShelfCard key={s.id} code={s.code} intel={intel} state={state} />
                      )
                    })}
                  {zonesWithShelves.map(({ zone, shelves: groupShelves }) => (
                    <div key={zone.id} className="space-y-3">
                      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                        <IconStore className="h-3.5 w-3.5 text-gray-400" /> {zone.name}
                      </p>
                      <div className="space-y-3">
                        {groupShelves.map((s) => {
                          const intel = intelByCode.get(s.code)
                          const state = intel ? SHELF_STATE[intel.detection_status] ?? SHELF_STATE.UNKNOWN : SHELF_STATE.UNKNOWN
                          return <ShelfCard key={s.id} code={s.code} intel={intel} state={state} />
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {shelfIntel.length > 0 && (
                <p className="mt-4 text-xs text-gray-400">
                  {regionsWithData} of {shelfIntel.length} regions have fresh AI data. Occupancy is estimated from visible facings — it never adjusts inventory.
                </p>
              )}
            </Card>

            {/* Right rail */}
            <div className="space-y-6">
              <Card
                title="Cameras"
                subtitle="Local edge devices feeding the AI runtime"
                action={
                  <Link to="/app/cameras" className="text-xs font-medium text-brand-700 hover:underline">
                    Manage →
                  </Link>
                }
              >
                {cameras.length === 0 ? (
                  <EmptyState title="No cameras yet" hint="Register a camera to start the pipeline." />
                ) : (
                  <div className="space-y-2">
                    {cameras.map((c) => {
                      const last = obs
                        .filter((o) => o.camera_id === c.id)
                        .slice()
                        .sort((a, b) => b.observed_at.localeCompare(a.observed_at))[0]
                      return (
                        <div key={c.id} className="flex items-center justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span
                              className={`inline-block h-2 w-2 shrink-0 rounded-full ${c.is_active ? 'bg-emerald-500' : 'bg-gray-300'}`}
                              aria-hidden="true"
                            />
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-gray-800">{cleanName(c.name)}</p>
                              <p className="truncate text-xs text-gray-500">{c.location ?? 'Unlocated'}</p>
                            </div>
                          </div>
                          <span className="shrink-0 text-xs text-gray-400">
                            {last ? new Date(last.observed_at).toLocaleTimeString() : 'no detections'}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Card>

              <Card title="Live detections" subtitle="Newest product observations from the Edge AI">
                {recentProductObs.length === 0 ? (
                  <EmptyState title="No detections yet" hint="When the runtime observes products they appear here in near real-time." />
                ) : (
                  <div className="divide-y divide-gray-100">
                    {recentProductObs.map((o) => (
                      <div key={o.id} className="flex items-center justify-between py-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm text-gray-700">{o.text ?? 'Product detection'}</p>
                          <p className="text-xs text-gray-400">
                            {o.camera_id ? `camera ${o.camera_id.slice(0, 8)}` : 'edge'} · {new Date(o.observed_at).toLocaleTimeString()}
                          </p>
                        </div>
                        {o.confidence != null && (
                          <Badge tone={o.confidence > 0.7 ? 'green' : 'amber'}>{Math.round(o.confidence * 100)}%</Badge>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </div>

          {/* Watchlist: mapped vs unmapped */}
          {productIntel.length > 0 && (
            <Card
              title="Visible product watchlist"
              subtitle="Comparison against inventory — read-only digest, never auto-adjusts stock"
              action={
                <Link to="/app/product-intelligence" className="text-xs font-medium text-brand-700 hover:underline">
                  Full analysis →
                </Link>
              }
            >
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {productIntel.slice(0, 12).map((p) => (
                  <div key={p.ai_class + (p.product_id ?? '')} className="rounded-lg border border-gray-100 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-medium text-gray-800">{p.product_name ?? p.ai_class}</p>
                      <Badge tone={COMPARISON_TONE[p.comparison_status] ?? 'gray'}>{p.comparison_status.split('_').join(' ')}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-gray-500 tabular">
                      visible <span className="font-semibold text-gray-900">{p.visible_count}</span>
                      {p.database_quantity != null && (
                        <> · recorded <span className="font-semibold text-gray-900">{p.database_quantity}</span></>
                      )}
                    </p>
                    {p.shelf_code && <p className="mt-0.5 text-xs text-gray-400">shelf {p.shelf_code}</p>}
                    {p.confidence != null && (
                      <MiniProgress value={p.confidence * 100} color="#3b82f6" />
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

function ShelfCard({
  code,
  intel,
  state,
}: {
  code: string
  intel: ShelfIntelligenceRow | undefined
  state: { label: string; tone: 'green' | 'amber' | 'red' | 'gray' | 'blue' }
}) {
  const pct = intel?.occupied_pct ?? null
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-sm font-semibold text-brand-900">{code}</p>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      {pct != null ? (
        <div className="mt-2">
          <MiniProgress value={pct} color={pct < 45 ? '#d97706' : pct < 70 ? '#3b82f6' : '#059669'} />
        </div>
      ) : (
        <p className="mt-2 text-xs text-gray-400">No AI data yet</p>
      )}
      {intel && intel.visible_products.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {intel.visible_products.slice(0, 4).map((vp) => (
            <span
              key={vp.ai_class}
              className="rounded-md bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600 ring-1 ring-inset ring-gray-200"
            >
              {vp.product_name ?? vp.ai_class} ×{vp.visible_count}
            </span>
          ))}
          {intel.visible_products.length > 4 && (
            <span className="text-[11px] text-gray-400">+{intel.visible_products.length - 4}</span>
          )}
        </div>
      )}
    </div>
  )
}