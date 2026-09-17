import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Stat, PageHeader } from '../components/ui/Card'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { Badge } from '../components/ui/Badge'
import { EdgeNodeStatus } from '../components/EdgeNodeStatus'
import { LineChart } from '../components/ui/charts'
import { useEdge } from '../edge/EdgeContext'
import { cleanName } from '../lib/cleanNames'
import { productApi } from '../lib/api/products'
import { cameraApi } from '../lib/api/cameras'
import { billApi } from '../lib/api/bills'
import { saleApi } from '../lib/api/sales'
import { observationApi } from '../lib/api/observations'
import { reconciliationApi } from '../lib/api/reconciliation'
import { inventoryApi } from '../lib/api/inventory'
import { intelligenceApi } from '../lib/api/intelligence'
import { alertApi } from '../lib/api/alerts'
import { insightApi } from '../lib/api/insights'
import { demoApi } from '../lib/api/demo'
import type {
  AISummary,
  Alert,
  Batch,
  Camera,
  DemoScenarioStatus,
  InsightSummary,
  Inventory,
  Observation,
  Product,
  ReconciliationResult,
  Sale,
  Store,
  StoreHealthMetrics,
} from '../lib/api/types'
import { storeApi } from '../lib/api/zone'
import {
  IconAlert,
  IconArrowUpRight,
  IconBox,
  IconCheck,
  IconReceipt,
  IconRupee,
  IconSparkle,
  IconTrendUp,
} from '../components/ui/icons'

const LOW_STOCK_THRESHOLD = 10 // mirrored from backend settings default
const EXPIRY_WARNING_DAYS = 30
const DAY_MS = 86_400_000

function isSameDay(iso: string): boolean {
  const d = new Date(iso)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

function daysUntil(iso: string): number {
  const then = new Date(iso).getTime()
  const now = Date.now()
  return Math.ceil((then - now) / DAY_MS)
}

function last7DayLabels(): string[] {
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(Date.now() - (6 - i) * DAY_MS)
    return d.toLocaleDateString(undefined, { weekday: 'short' })
  })
}

function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

export function DashboardPage() {
  const { edgeOnline } = useEdge().status
  const [store, setStore] = useState<Store | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [inventory, setInventory] = useState<Inventory[]>([])
  const [batches, setBatches] = useState<Batch[]>([])
  const [observations, setObservations] = useState<Observation[]>([])
  const [recon, setRecon] = useState<ReconciliationResult[]>([])
  const [billsToday, setBillsToday] = useState(0)
  const [sales, setSales] = useState<Sale[]>([])
  const [aiSummary, setAiSummary] = useState<AISummary | null>(null)
  const [listAlerts, setListAlerts] = useState<Alert[]>([])
  const [insightSummary, setInsightSummary] = useState<InsightSummary | null>(null)
  const [storeHealth, setStoreHealth] = useState<StoreHealthMetrics | null>(null)
  const [demoStatus, setDemoStatus] = useState<DemoScenarioStatus | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
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
        // store endpoint may be down; other calls still attempted
      }

      const [camRes, prodRes, obsRes, recRes, batchRes] = await Promise.all([
        cameraApi.list(sid ? { store_id: sid } : undefined),
        productApi.list(sid ? { store_id: sid } : undefined),
        observationApi.list(),
        reconciliationApi.list(),
        inventoryApi.listAllBatches(),
      ])
      setCameras(camRes.items)
      setProducts(prodRes.items)
      setObservations(obsRes.items)
      setRecon(recRes.items)
      setBatches(batchRes.items ?? [])

      if (sid) {
        try {
          const ai = await intelligenceApi.summary({ store_id: sid })
          setAiSummary(ai)
        } catch {
          setAiSummary(null) // summary endpoint optional on the dashboard
        }

        try {
          const alertRes = await alertApi.list({ store_id: sid, limit: 10 })
          setListAlerts(alertRes.items)
        } catch {
          setListAlerts([]) // alert centre optional on the dashboard
        }

        try {
          const ins = await insightApi.summary(sid)
          setInsightSummary(ins)
        } catch {
          setInsightSummary(null) // store intelligence optional on the dashboard
        }
        try {
          const health = await insightApi.storeHealth(sid)
          setStoreHealth(health)
        } catch {
          setStoreHealth(null)
        }
        try {
          setDemoStatus(await demoApi.status())
        } catch {
          setDemoStatus(null) // showcase scenario optional on the dashboard
        }
      }

      if (sid && prodRes.items.length > 0) {
        // Aggregate stock is per-product only; fetch the first 40 in parallel.
        const productIds = prodRes.items.slice(0, 40).map((p) => p.id)
        const invResults = await Promise.all(
          productIds.map((pid) =>
            inventoryApi
              .getProductInventory(sid as string, pid)
              .then((inv) => ({ ok: true as const, inv }))
              .catch(() => ({ ok: false as const, inv: null as unknown as Inventory })),
          ),
        )
        setInventory(invResults.filter((r) => r.ok).map((r) => r.inv))

        try {
          const bills = await billApi.list({ store_id: sid })
          setBillsToday(bills.items.filter((b) => isSameDay(b.created_at)).length)
        } catch {
          setBillsToday(0)
        }
        try {
          const salesRes = await saleApi.list({ store_id: sid })
          setSales(salesRes.items)
        } catch {
          setSales([])
        }
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

  const activeCameraCount = cameras.filter((c) => c.is_active).length
  const totalStock = inventory.reduce((sum, i) => sum + i.quantity, 0)

  const productNameById = new Map(products.map((p) => [p.id, p.name]))
  const recentBatches = batches
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5)

  const stockByProduct = new Map(inventory.map((i) => [i.product_id, i]))
  const lowStockCount = products.filter((p) => {
    const inv = stockByProduct.get(p.id)
    if (!p.is_active) return false
    const qty = inv?.quantity ?? 0
    const reorderLevel = inv?.reorder_level ?? 0
    return qty <= (reorderLevel > 0 ? reorderLevel : LOW_STOCK_THRESHOLD)
  }).length

  const expiringOrExpired = batches.filter((b) => {
    if (!b.expiry_date) return false
    return daysUntil(b.expiry_date) <= EXPIRY_WARNING_DAYS
  })

  const salesToday = sales.filter((s) => isSameDay(s.sale_timestamp_utc))
  const salesTotalToday = salesToday.reduce((sum, s) => sum + Number(s.total), 0)
  const recentObs = observations.slice(0, 6)
  const personObsCount = observations.filter((o) => o.observation_type === 'PERSON').length
  const alerts = recon.filter((r) => r.status !== 'MATCH').slice(0, 5)
  const openAlertCount = listAlerts.filter((a) => a.status === 'OPEN').length
  const highCriticalAlertCount = listAlerts.filter(
    (a) => a.severity === 'HIGH' || a.severity === 'CRITICAL',
  ).length

  // 7-day sales trend grouped by local day (calendar-aligned, not rolling).
  const last7 = Array.from({ length: 7 }, (_, i) => Date.now() - (6 - i) * DAY_MS)
  const saleBuckets = last7.map((ts) => {
    const key = dayKey(new Date(ts).toISOString())
    return sales.filter((s) => dayKey(s.sale_timestamp_utc) === key).reduce((sum, s) => sum + Number(s.total), 0)
  })
  const hasSaleHistory = sales.length > 0

  const lowStockProducts = products
    .filter((p) => {
      const inv = stockByProduct.get(p.id)
      if (!p.is_active) return false
      const qty = inv?.quantity ?? 0
      return qty <= LOW_STOCK_THRESHOLD
    })
    .slice(0, 8)

  const ReconBadge = ({ status }: { status: string }) => {
    const tone =
      status === 'MATCH'
        ? 'green'
        : status === 'POSSIBLE_SHORTAGE'
          ? 'red'
          : status === 'POSSIBLE_SURPLUS'
            ? 'amber'
            : 'purple'
    return <Badge tone={tone}>{status}</Badge>
  }

  const kpiCards = [
    {
      label: 'Total Products',
      value: products.length,
      icon: <IconBox className="h-4 w-4 text-brand-600" />,
      hint: 'active SKUs',
      tone: 'brand' as const,
    },
    {
      label: 'Current Stock',
      value: totalStock.toLocaleString('en-IN'),
      icon: <IconCheck className="h-4 w-4 text-emerald-600" />,
      hint: 'units across fetched SKUs',
      tone: 'positive' as const,
    },
    {
      label: 'Low Stock',
      value: lowStockCount,
      icon: <IconAlert className="h-4 w-4 text-amber-600" />,
      hint: lowStockCount > 0 ? 'reorder soon' : 'all healthy',
      tone: lowStockCount > 0 ? ('warning' as const) : ('default' as const),
    },
    {
      label: 'Expiring ≤30d',
      value: expiringOrExpired.length,
      icon: <IconAlert className="h-4 w-4 text-red-600" />,
      hint: 'batches near/over expiry',
      tone: expiringOrExpired.length > 0 ? ('danger' as const) : ('default' as const),
    },
    {
      label: "Today's Bills",
      value: billsToday,
      icon: <IconReceipt className="h-4 w-4 text-gray-500" />,
      hint: 'bills created today',
      tone: 'default' as const,
    },
    {
      label: 'Sales Today',
      value: `₹${salesTotalToday.toLocaleString('en-IN')}`,
      icon: <IconRupee className="h-4 w-4 text-brand-600" />,
      hint: salesToday.length > 0 ? `${salesToday.length} sale line(s)` : undefined,
      tone: 'brand' as const,
    },
  ]

  const aiFlags =
    aiSummary == null
      ? 0
      : aiSummary.reconciliation.possible_shortages +
        aiSummary.reconciliation.possible_surpluses +
        aiSummary.shelves.possible_misplacements

  return (
    <div className="page-shell space-y-6">
      {/* Header */}
      <PageHeader
        eyebrow="Operations overview"
        title={
          <>
            {store ? cleanName(store.name) : 'Storeye Dashboard'}
          </>
        }
        trailing={
          <>
            <span className="hidden text-xs text-gray-500 sm:block">
              {edgeOnline ? 'Live snapshot' : 'Last known good data'}
            </span>
            <EdgeNodeStatus compact />
          </>
        }
      />

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading dashboard…" />
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
            {kpiCards.map((k) => (
              <Stat key={k.label} {...k} />
            ))}
          </div>

          {/* AI insight + sales trend band */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Card
              className="xl:col-span-2"
              title="7-day sales trend"
              subtitle="Billed totals by day from real sales records"
              action={
                <Link to="/app/reports" className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
                  Reports <IconArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              }
            >
              {!hasSaleHistory ? (
                <EmptyState title="No sales yet" hint="Create a bill to start the trend." />
              ) : (
                <>
                  <div className="overflow-hidden rounded-xl border border-gray-200 bg-white px-3 py-4">
                    <LineChart
                      values={saleBuckets}
                      labels={last7DayLabels()}
                      color="#3b82f6"
                      dotStroke="#3b82f6"
                      lineShadowY={3}
                      height={150}
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
                    <span className="inline-flex items-center gap-1">
                      <IconTrendUp className="h-3.5 w-3.5 text-emerald-600" />
                      Daily billed total (₹)
                    </span>
                    <span className="tabular">7 days</span>
                  </div>
                </>
              )}
            </Card>

            <Card
              title="AI snapshot"
              subtitle="Derived from real Edge AI detections — informational only"
              action={
                <Link to="/app/shelf-intelligence" className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
                  Shelves <IconArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              }
            >
              {aiSummary == null ? (
                <EmptyState
                  title="AI summary unavailable"
                  hint="Open the Product/Shelf intelligence pages when the AI pipeline is running."
                />
              ) : (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                    <span className="flex items-center gap-2 text-sm text-gray-600">
                      <IconBox className="h-4 w-4 text-brand-600" /> Visible products
                    </span>
                    <span className="text-sm font-semibold text-gray-900 tabular">
                      {aiSummary.products.total_visible_quantity}
                      <span className="font-normal text-gray-400"> in {aiSummary.products.visible_classes} class(es)</span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                    <span className="flex items-center gap-2 text-sm text-gray-600">
                      <IconAlert className="h-4 w-4 text-amber-600" /> Shelves to refill
                    </span>
                    <span className={`text-sm font-semibold tabular ${aiSummary.shelves.low_visible + aiSummary.shelves.empty_visible ? 'text-amber-600' : 'text-gray-900'}`}>
                      {aiSummary.shelves.low_visible + aiSummary.shelves.empty_visible}
                    </span>
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                    <span className="flex items-center gap-2 text-sm text-gray-600">
                      <IconSparkle className="h-4 w-4 text-gold-700" /> AI flags
                    </span>
                    <span className={`text-sm font-semibold tabular ${aiFlags ? 'text-red-600' : 'text-gray-900'}`}>{aiFlags}</span>
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                    <span className="flex items-center gap-2 text-sm text-gray-600">People tracked</span>
                    <span className="text-sm font-semibold text-gray-900 tabular">{aiSummary.people.distinct_tracks}</span>
                  </div>
                </div>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* Left column */}
            <div className="space-y-6 lg:col-span-2">
              <Card
                title="Recent AI Observations"
                subtitle="Latest detections recorded by the Edge AI runtime"
                action={
                  <Link to="/app/observations" className="text-xs font-medium text-brand-700 hover:underline">
                    View all →
                  </Link>
                }
              >
                {recentObs.length === 0 ? (
                  <EmptyState
                    title="No observations yet"
                    hint="Run the Edge AI runtime to start collecting detections."
                  />
                ) : (
                  <div className="divide-y divide-gray-100">
                    {recentObs.map((o) => (
                      <div key={o.id} className="flex items-center justify-between py-2.5">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Badge tone="blue">{o.observation_type}</Badge>
                            {o.confidence != null && (
                              <span className="text-xs text-gray-400">
                                {Math.round(o.confidence * 100)}%
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 truncate text-sm text-gray-600">
                            {o.text ?? o.observation_type}
                            {o.track_id != null && ` · track #${o.track_id}`}
                          </p>
                        </div>
                        <span className="ml-3 shrink-0 text-xs text-gray-400">
                          {new Date(o.observed_at).toLocaleTimeString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card
                title="Low Stock Watch"
                subtitle="From live inventory API (informational)"
                action={
                  <Link to="/app/inventory" className="text-xs font-medium text-brand-700 hover:underline">
                    Inventory →
                  </Link>
                }
              >
                {lowStockProducts.length === 0 ? (
                  <EmptyState title="No low-stock products right now" hint="Everything is at or above threshold." />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table-base w-full text-left">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th>Product</th>
                          <th>SKU</th>
                          <th>Stock</th>
                          <th>Reorder Level</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {lowStockProducts.map((p) => {
                          const inv = stockByProduct.get(p.id)
                          return (
                            <tr key={p.id}>
                              <td className="font-medium text-gray-800">{p.name}</td>
                              <td className="text-gray-500">{p.sku}</td>
                              <td>
                                <Badge tone={inv && inv.quantity > 0 ? 'amber' : 'red'}>
                                  {inv?.quantity ?? 0}
                                </Badge>
                              </td>
                              <td className="text-gray-500">{inv?.reorder_level ?? 0}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {/* M17: Smart Batch Receiving entry + recent real intakes */}
              <Card
                title="Smart Batch Receiving"
                subtitle="Close-up package scan → OCR → human-confirmed receipt (real batches)"
                action={
                  <Link to="/app/inventory/receive" className="text-xs font-medium text-brand-700 hover:underline">
                    Open →
                  </Link>
                }
              >
                <p className="mb-3 text-sm text-gray-600">
                  Photograph a pack close-up: the local barcode + OCR reads product,
                  batch, MFG, EXP and MRP. Review and confirm before stock moves.
                </p>
                {recentBatches.length === 0 ? (
                  <EmptyState
                    title="No batches received yet"
                    hint="Use “+ Receive New Stock” to scan the first package."
                    action={
                      <Link to="/app/inventory/receive">
                        <span className="btn-primary">+ Receive New Stock</span>
                      </Link>
                    }
                  />
                ) : (
                  <>
                    <ul className="divide-y divide-gray-100">
                      {recentBatches.map((b) => (
                        <li key={b.id} className="flex items-center justify-between gap-2 py-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-gray-800">
                              {productNameById.get(b.product_id) ?? b.product_id.slice(0, 8)}
                            </p>
                            <p className="text-xs text-gray-500">
                              {b.quantity} unit(s)
                              {b.batch_number ? <> · <span className="font-mono">{b.batch_number}</span></> : null}
                            </p>
                          </div>
                          <div className="shrink-0 text-right">
                            {b.expiry_date ? (
                              <Badge tone={daysUntil(b.expiry_date) <= EXPIRY_WARNING_DAYS ? 'red' : 'green'}>
                                exp {b.expiry_date}
                              </Badge>
                            ) : (
                              <Badge tone="gray">no exp</Badge>
                            )}
                            <p className="mt-1 text-xs text-gray-400">
                              {new Date(b.created_at).toLocaleDateString()}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                    <div className="mt-2">
                      <Link to="/app/inventory/receive">
                        <span className="btn-primary">+ Receive New Stock</span>
                      </Link>
                    </div>
                  </>
                )}
              </Card>
            </div>

            {/* Right column */}
            <div className="space-y-6">
              <Card
                title="AI Runtime"
                subtitle="People tracked and cameras online"
                action={
                  <Link to="/app/cameras" className="text-xs font-medium text-brand-700 hover:underline">
                    Cameras →
                  </Link>
                }
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">Active Cameras</p>
                    <p className="text-2xl font-bold text-gray-900">{activeCameraCount}/{cameras.length}</p>
                  </div>
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">People Detected</p>
                    <p className="text-2xl font-bold text-gray-900">{personObsCount}</p>
                  </div>
                </div>
                <div className="mt-3">
                  <Link to="/app/cameras" className="text-sm font-medium text-brand-700 hover:underline">
                    Open camera dashboard →
                  </Link>
                </div>
              </Card>

              <Card
                title="Showcase Scenario"
                subtitle="Deterministic demo state applied by the backend"
                action={
                  <Link to="/app/demo" className="text-xs font-medium text-brand-700 hover:underline">
                    Control →
                  </Link>
                }
              >
                {demoStatus == null ? (
                  <EmptyState
                    title="Showcase unavailable"
                    hint="Demo mode is disabled, or the demo store is not seeded."
                  />
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                      <span className="text-xs text-gray-500">Active scenario</span>
                      <span className="text-sm font-semibold text-gray-900">
                        {demoStatus.scenario?.name ?? '—'}
                      </span>
                    </div>
                    {demoStatus.scenario?.description ? (
                      <p className="text-xs text-gray-500">{demoStatus.scenario.description}</p>
                    ) : null}
                    <Link
                      to="/app/demo"
                      className="inline-flex text-sm font-medium text-brand-700 hover:underline"
                    >
                      Switch scenario →
                    </Link>
                  </div>
                )}
              </Card>

              <Card
                title="Store Intelligence"
                subtitle="Insights with evidence — no automated stock changes"
                action={
                  <Link to="/app/insights" className="text-xs font-medium text-brand-700 hover:underline">
                    Insights →
                  </Link>
                }
              >
                {insightSummary == null ? (
                  <EmptyState
                    title="No insights yet"
                    hint="Run “Evaluate now” from the Insights page."
                  />
                ) : (
                  <>
                    <div className="mb-3 grid grid-cols-2 gap-3">
                      <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                        <p className="text-xs text-gray-500">State</p>
                        <p
                          className={`text-2xl font-bold ${
                            storeHealth?.state === 'CRITICAL'
                              ? 'text-red-600'
                              : storeHealth?.state === 'ATTENTION'
                                ? 'text-amber-600'
                                : storeHealth?.state === 'HEALTHY'
                                  ? 'text-emerald-700'
                                  : 'text-gray-900'
                          }`}
                        >
                          {storeHealth?.state ?? '—'}
                        </p>
                      </div>
                      <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                        <p className="text-xs text-gray-500">Open insights</p>
                        <p className={`text-2xl font-bold ${insightSummary.open ? 'text-amber-600' : 'text-gray-900'}`}>
                          {insightSummary.open}
                        </p>
                      </div>
                    </div>
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {storeHealth && storeHealth.basis.slice(0, 2).map((line) => (
                        <Badge key={line} tone="gray">
                          {line}
                        </Badge>
                      ))}
                    </div>
                    <div className="mb-2 space-y-1.5">
                      {insightSummary.by_type &&
                        Object.entries(insightSummary.by_type)
                          .sort((a, b) => b[1] - a[1])
                          .slice(0, 3)
                          .map(([cat, count]) => (
                            <div
                              key={cat}
                              className="flex items-center justify-between text-sm"
                            >
                              <span className="text-gray-600">{cat}</span>
                              <span className="font-semibold text-gray-900 tabular">{count}</span>
                            </div>
                          ))}
                    </div>
                    {insightSummary.high_priority > 0 ? (
                      <p className="text-xs font-medium text-red-600">
                        {insightSummary.high_priority} high-priority open
                      </p>
                    ) : (
                      <p className="text-xs text-gray-500">No high-priority open insights.</p>
                    )}
                  </>
                )}
              </Card>

              <Card
                title="Alerts"
                subtitle="Actionable intelligence — informational only, never auto-adjusts stock"
                action={
                  <Link to="/app/alerts" className="text-xs font-medium text-brand-700 hover:underline">
                    All →
                  </Link>
                }
              >
                {listAlerts.length === 0 ? (
                  <EmptyState
                    title="No alerts yet"
                    hint="Run the alert rules from the Alerts page after the Edge AI has observed your shelves."
                  />
                ) : (
                  <>
                    <div className="mb-3 grid grid-cols-2 gap-3">
                      <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                        <p className="text-xs text-gray-500">Open</p>
                        <p className={`text-2xl font-bold ${openAlertCount ? 'text-amber-600' : 'text-gray-900'}`}>
                          {openAlertCount}
                        </p>
                      </div>
                      <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                        <p className="text-xs text-gray-500">High / Critical</p>
                        <p className={`text-2xl font-bold ${highCriticalAlertCount ? 'text-red-600' : 'text-gray-900'}`}>
                          {highCriticalAlertCount}
                        </p>
                      </div>
                    </div>
                    <div className="space-y-2">
                      {listAlerts.slice(0, 5).map((a) => (
                        <div key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-gray-800">{a.title}</p>
                            <p className="text-xs text-gray-500">
                              {a.alert_type} · {a.status}
                            </p>
                          </div>
                          <Badge
                            tone={
                              a.severity === 'CRITICAL' || a.severity === 'HIGH'
                                ? 'red'
                                : a.severity === 'MEDIUM'
                                  ? 'amber'
                                  : 'blue'
                            }
                          >
                            {a.severity}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </Card>

              <Card
                title="Reconciliation Alerts"
                subtitle="Informational only — never auto-corrects inventory"
                action={
                  <Link to="/app/reconciliation" className="text-xs font-medium text-brand-700 hover:underline">
                    All →
                  </Link>
                }
              >
                {alerts.length === 0 ? (
                  <EmptyState title="No reconciliation alerts" hint="When AI counts diverge from stock, alerts appear here." />
                ) : (
                  <div className="space-y-2">
                    {alerts.map((r) => (
                      <div key={r.id} className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                        <div>
                          <p className="text-sm font-medium text-gray-800">
                            {r.product_id.slice(0, 8)}…
                          </p>
                          <p className="text-xs text-gray-500">
                            DB {r.database_quantity} vs AI {r.ai_observed_quantity}
                          </p>
                        </div>
                        <ReconBadge status={r.status} />
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  )
}