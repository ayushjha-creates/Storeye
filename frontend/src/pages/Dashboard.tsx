// M28: shopkeeper-first Home page.
//
// Answer five questions immediately: how much did I sell today, what stock do I
// have, what is running low, what needs my attention, and what should I do
// next. Every number on this page comes from a real API — nothing is hardcoded.
// Advanced AI detail lives under Settings → Advanced; Home only surfaces
// business outcomes.

import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { Spinner } from '../components/ui/Spinner'
import { Badge } from '../components/ui/Badge'
import { EmptyState } from '../components/ui/ErrorState'
import { LineChart } from '../components/ui/charts'
import { FootfallChart } from '../components/footfall/FootfallChart'
import { useAuth } from '../auth/AuthContext'
import { useEdge } from '../edge/EdgeContext'
import { billApi } from '../lib/api/bills'
import { edgeApi } from '../lib/api/edge'
import { intelligenceApi } from '../lib/api/intelligence'
import { inventoryApi } from '../lib/api/inventory'
import { journeyApi } from '../lib/api/journeys'
import { mobileIntakeApi } from '../lib/api/mobileIntake'
import { productApi } from '../lib/api/products'
import { saleApi } from '../lib/api/sales'
import { storeApi } from '../lib/api/zone'
import { EMPTY_COPY, expiryLabel, formatINR, greeting } from '../lib/shop'
import type {
  AISummary,
  Batch,
  DailyFootfallPoint,
  EdgeCameraStatus,
  Inventory,
  Product,
  Sale,
  Store,
} from '../lib/api/types'
import {
  IconAlert,
  IconArrowUpRight,
  IconBox,
  IconCalendar,
  IconCheck,
  IconChevronRight,
  IconClock,
  IconReceipt,
  IconRupee,
  IconScan,
} from '../components/ui/icons'

const LOW_STOCK_THRESHOLD = 10
const EXPIRY_WARNING_DAYS = 30
const DAY_MS = 86_400_000

function isSameDay(iso: string): boolean {
  const d = new Date(iso)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / DAY_MS)
}

function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function weekday(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' })
}

function formatDwell(sec: number | null): string {
  if (sec == null || sec <= 0) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  if (m === 0) return `${s}s`
  return `${m}m ${s}s`
}

type Attention = { id: string; icon: string; text: string; to: string }

export function DashboardPage() {
  const { session } = useAuth()
  const { status } = useEdge()
  const [store, setStore] = useState<Store | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [inventory, setInventory] = useState<Inventory[]>([])
  const [batches, setBatches] = useState<Batch[]>([])
  const [sales, setSales] = useState<Sale[]>([])
  const [billsToday, setBillsToday] = useState(0)
  const [aiSummary, setAiSummary] = useState<AISummary | null>(null)
  const [footfall, setFootfall] = useState<DailyFootfallPoint[]>([])
  const [visitorsToday, setVisitorsToday] = useState<number | null>(null)
  const [avgDwellSeconds, setAvgDwellSeconds] = useState<number | null>(null)
  const [pendingReceipts, setPendingReceipts] = useState(0)
  const [edgeCameras, setEdgeCameras] = useState<EdgeCameraStatus[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    let sid: string | null = null
    try {
      try {
        const stores = await storeApi.list()
        const first = stores.items[0]
        if (first) {
          sid = first.id
          setStore(first)
        }
      } catch {
        // store list optional so the rest of the page still loads
      }

      const [prodRes, batchRes] = await Promise.all([
        productApi.list(sid ? { store_id: sid } : undefined),
        inventoryApi.listAllBatches(),
      ])
      setProducts(prodRes.items)
      setBatches(batchRes.items ?? [])

      if (sid && prodRes.items.length > 0) {
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

      if (sid) {
        try {
          const ai = await intelligenceApi.summary({ store_id: sid })
          setAiSummary(ai)
        } catch {
          setAiSummary(null)
        }
        try {
          const daily = await journeyApi.daily({ store_id: sid, days: 7 })
          setFootfall(daily.items)
        } catch {
          setFootfall([])
        }
        try {
          const end = new Date().toISOString()
          const start = new Date(Date.now() - 24 * 3600 * 1000).toISOString()
          const sum = await journeyApi.summary({ store_id: sid, start, end })
          setVisitorsToday(sum.total_visitors)
          const dwell = sum.avg_visit_duration_seconds ?? sum.avg_zone_dwell_seconds ?? null
          setAvgDwellSeconds(dwell != null && dwell > 0 ? dwell : null)
        } catch {
          setVisitorsToday(null)
          setAvgDwellSeconds(null)
        }
      }

      try {
        const jobs = await mobileIntakeApi.jobs()
        const pending = jobs.items.filter(
          (j) => j.state !== 'CONFIRMED' && j.state !== 'PROCESSED' && j.state !== 'FAILED',
        )
        setPendingReceipts(pending.length)
      } catch {
        setPendingReceipts(0)
      }
      try {
        const cams = await edgeApi.cameras()
        setEdgeCameras(Array.isArray(cams) ? cams : [])
      } catch {
        setEdgeCameras([])
      }
    } catch {
      // Home degrades gracefully: each metric is independently best-effort.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const stockByProduct = new Map(inventory.map((i) => [i.product_id, i]))
  const totalStock = inventory.reduce((sum, i) => sum + i.quantity, 0)

  const isLow = (p: Product): boolean => {
    if (!p.is_active) return false
    const inv = stockByProduct.get(p.id)
    const qty = inv?.quantity ?? 0
    const reorderLevel = inv?.reorder_level ?? 0
    return qty > 0 && qty <= (reorderLevel > 0 ? reorderLevel : LOW_STOCK_THRESHOLD)
  }
  const isOut = (p: Product): boolean => {
    if (!p.is_active) return false
    return (stockByProduct.get(p.id)?.quantity ?? 0) <= 0
  }

  const lowStockCount = products.filter(isLow).length
  const outOfStockCount = products.filter(isOut).length

  const expiring = batches.filter((b) => {
    if (!b.expiry_date) return false
    return daysUntil(b.expiry_date) <= EXPIRY_WARNING_DAYS
  })
  const expiringSoonCount = expiring.filter((b) => b.expiry_date && daysUntil(b.expiry_date) >= 0).length
  const expiredCount = expiring.filter((b) => b.expiry_date && daysUntil(b.expiry_date) < 0).length

  const salesToday = sales.filter((s) => isSameDay(s.sale_timestamp_utc))
  const salesTotalToday = salesToday.reduce((sum, s) => sum + Number(s.total), 0)

  const healthyCams = edgeCameras.filter((c) => c.health === 'RUNNING' || c.health === 'DEGRADED')
  const problematicCams = edgeCameras.filter((c) => c.health !== 'RUNNING' && c.health !== 'DEGRADED')
  const offlineCamNames = problematicCams.map((c) => c.name).filter(Boolean)

  // Last-7-days sales trend (calendar-aligned, local day).
  const last7 = Array.from({ length: 7 }, (_, i) => Date.now() - (6 - i) * DAY_MS)
  const saleBuckets = last7.map((ts) => {
    const key = dayKey(new Date(ts).toISOString())
    return sales.filter((s) => dayKey(s.sale_timestamp_utc) === key).reduce((sum, s) => sum + Number(s.total), 0)
  })
  const salesLabels = last7.map((ts) => new Date(ts).toLocaleDateString(undefined, { weekday: 'short' }))

  const shelfCount = (aiSummary?.shelves?.low_visible ?? 0) + (aiSummary?.shelves?.empty_visible ?? 0)

  // WHAT NEEDS YOUR ATTENTION — only real active issues.
  const attention: Attention[] = []
  if (outOfStockCount > 0)
    attention.push({
      id: 'oos',
      icon: '🔴',
      text: `${outOfStockCount} ${outOfStockCount === 1 ? 'product is' : 'products are'} out of stock`,
      to: '/app/stock',
    })
  if (lowStockCount > 0)
    attention.push({
      id: 'low',
      icon: '🟡',
      text: `${lowStockCount} ${lowStockCount === 1 ? 'product is' : 'products are'} running low`,
      to: '/app/stock',
    })
  if (expiredCount > 0)
    attention.push({
      id: 'expired',
      icon: '⏰',
      text: `${expiredCount} ${expiredCount === 1 ? 'batch has' : 'batches have'} expired`,
      to: '/app/stock',
    })
  else if (expiringSoonCount > 0)
    attention.push({
      id: 'expiry',
      icon: '⏰',
      text: `${expiringSoonCount} ${expiringSoonCount === 1 ? 'batch is' : 'batches are'} expiring soon`,
      to: '/app/stock',
    })
  if (pendingReceipts > 0)
    attention.push({
      id: 'receipt',
      icon: '📥',
      text: `${pendingReceipts} stock ${pendingReceipts === 1 ? 'receipt needs' : 'receipts need'} confirmation`,
      to: '/app/receive',
    })
  if (offlineCamNames.length > 0)
    attention.push({
      id: 'cam',
      icon: '📷',
      text:
        offlineCamNames.length === 1
          ? `${offlineCamNames[0]} is offline`
          : `${offlineCamNames.length} cameras need attention`,
      to: '/app/cameras',
    })
  if (shelfCount > 0)
    attention.push({
      id: 'shelf',
      icon: '🍫',
      text: `${shelfCount} ${shelfCount === 1 ? 'shelf' : 'shelves'} may need restocking`,
      to: '/app/stock',
    })

  const hasAttention = attention.length > 0

  const storeStatus: { label: string; tone: 'green' | 'amber' } = offlineCamNames.length > 0
    ? { label: `⚠ ${offlineCamNames.length === 1 ? 'One camera' : `${offlineCamNames.length} cameras`} need attention`, tone: 'amber' }
    : status.edgeOnline
      ? { label: '● Store running normally', tone: 'green' }
      : { label: '● Offline mode — data still on this computer', tone: 'amber' }

  const firstName = (session?.userName ?? 'there').split(' ')[0]
  const storeName = store?.name ?? session?.storeName ?? 'Storeye'

  const footfallTotal = footfall.reduce((sum, p) => sum + p.visitors, 0)

  if (loading) {
    return (
      <div className="page-shell flex items-center justify-center py-20">
        <Spinner />
      </div>
    )
  }

  const QuickAction = ({ to, label, icon, primary = false }: { to: string; label: string; icon: ReactNode; primary?: boolean }) => (
    <Link
      to={to}
      className={`flex items-center justify-between gap-3 rounded-xl px-4 py-3.5 text-sm font-semibold shadow-sm transition-all duration-150 active:scale-[0.98] ${
        primary
          ? 'bg-brand-600 text-white hover:bg-brand-700 shadow-brand-500/15'
          : 'border border-gray-200/90 bg-white text-gray-800 hover:bg-gray-50/80 hover:border-gray-300/80'
      }`}
    >
      <span className="flex items-center gap-2.5">
        <span className={primary ? 'text-white' : 'text-brand-600'}>{icon}</span>
        {label}
      </span>
      <IconChevronRight className={`h-4 w-4 ${primary ? 'text-white/80' : 'text-gray-400'}`} />
    </Link>
  )

  return (
    <div className="page-shell space-y-6 p-4 sm:p-6">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-gray-900">
            {greeting()}, {firstName}
          </h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-gray-600">
            <span className="font-semibold text-gray-900">{storeName}</span>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${storeStatus.tone === 'green' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
              {storeStatus.label}
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/app/cameras" className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
            Cameras
          </Link>
          <Link to="/app/reports" className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
            Reports
          </Link>
        </div>
      </header>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Today's Sales" value={formatINR(salesTotalToday)} icon={<IconRupee />} tone="brand" hint={`${salesToday.length} sales`} />
        <Kpi label="Current Stock" value={`${totalStock.toLocaleString('en-IN')} units`} icon={<IconBox />} hint={`${products.length} products`} />
        <Kpi label="Running Low" value={String(lowStockCount + outOfStockCount)} icon={<IconAlert />} tone={lowStockCount + outOfStockCount > 0 ? 'warning' : 'default'} hint="needs restock" />
        <Kpi label="Expiring Soon" value={String(expiringSoonCount)} icon={<IconCalendar />} tone={expiringSoonCount > 0 ? 'warning' : 'default'} hint={`${expiredCount} already expired`} />
        <Kpi label="Today's Bills" value={String(billsToday)} icon={<IconReceipt />} />
        <Kpi label="Avg Dwell Time" value={formatDwell(avgDwellSeconds)} icon={<IconClock />} hint={visitorsToday != null && visitorsToday > 0 ? `${visitorsToday} visitors` : 'Per customer visit'} />
      </div>

      {/* What needs your attention */}
      <Card title="What needs your attention">
        {hasAttention ? (
          <ul className="divide-y divide-gray-100">
            {attention.slice(0, 6).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex items-center gap-2.5 text-sm text-gray-800">
                  <span aria-hidden="true">{a.icon}</span>
                  {a.text}
                </span>
                <Link to={a.to} className="flex shrink-0 items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700">
                  View <IconArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex items-start gap-3 py-1">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 ring-1 ring-inset ring-emerald-200">
              <IconCheck className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm font-semibold text-gray-900">{EMPTY_COPY.alerts}</p>
              <p className="mt-0.5 text-xs text-gray-500">Your store is running normally.</p>
            </div>
          </div>
        )}
      </Card>

      {/* Quick actions */}
      <section aria-label="Quick actions">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <QuickAction to="/app/receive" label="Receive Stock" icon={<IconScan />} primary />
          <QuickAction to="/app/sales" label="New Sale" icon={<IconRupee />} />
          <QuickAction to="/app/stock" label="Check Stock" icon={<IconBox />} />
          <QuickAction to="/app/alerts" label="View Alerts" icon={<IconAlert />} />
        </div>
      </section>

      {/* Charts */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Today's Sales" subtitle="Last 7 days">
          {sales.length > 0 ? (
            <LineChart values={saleBuckets} labels={salesLabels} color="#3b82f6" valueTextClass="fill-gray-900 tabular" />
          ) : (
            <EmptyState title={EMPTY_COPY.sales} hint="Sales appear here as you record bills." />
          )}
        </Card>

        <Card
          title="Total Store Footfalls"
          subtitle="Visitors counted by your cameras — last 7 days"
        >
          {footfallTotal > 0 ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold text-sky-700 tabular">
                    {footfallTotal}
                  </span>
                  <span className="text-xs text-gray-500">
                    {footfallTotal} visitors counted over {footfall.length} days
                  </span>
                </div>
                {footfall.length > 0 && (
                  <div className="flex items-center gap-4 rounded-lg bg-sky-50/70 px-3 py-2 text-xs text-sky-900">
                    <span>
                      Daily avg{' '}
                      <strong className="font-semibold tabular">
                        {Math.round(footfallTotal / footfall.length)}
                      </strong>
                    </span>
                    <span className="h-3 w-px bg-sky-200" />
                    <span>
                      Busiest{' '}
                      <strong className="font-semibold">
                        {weekday(
                          footfall.reduce(
                            (max, p) => (p.visitors > max.visitors ? p : max),
                            footfall[0],
                          ).date,
                        )}
                      </strong>
                      <span className="text-gray-500"> · </span>
                      <strong className="font-semibold tabular">
                        {
                          footfall.reduce(
                            (max, p) => (p.visitors > max.visitors ? p : max),
                            footfall[0],
                          ).visitors
                        }
                      </strong>
                    </span>
                  </div>
                )}
              </div>
              <FootfallChart
                data={footfall.map((p) => ({
                  label: isSameDay(p.date) ? 'Today' : weekday(p.date),
                  visitors: p.visitors,
                  date: p.date,
                  isToday: isSameDay(p.date),
                }))}
              />
            </div>
          ) : (
            <EmptyState
              title="No footfall recorded yet"
              hint="Footfall shows once people are detected at your cameras."
            />
          )}
        </Card>
      </div>

      {/* Activity + cameras */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Store activity" subtitle="What the store has seen recently">
          <dl className="space-y-2.5 text-sm">
            <ActivityRow label="Customers today" value={visitorsToday != null ? String(visitorsToday) : '—'} />
            <ActivityRow label="Average dwell time" value={formatDwell(avgDwellSeconds)} />
            <ActivityRow label="Products seen today" value={String(aiSummary?.products?.visible_classes ?? 0)} />
            <ActivityRow label="Shelves needing restock" value={String(shelfCount)} />
            <ActivityRow label="Busy today" value={aiSummary?.cameras ? 'Live cameras running' : '—'} />
          </dl>
        </Card>

        <Card
          title="Cameras"
          subtitle={edgeCameras.length > 0 ? `${edgeCameras.length} ${edgeCameras.length === 1 ? 'camera' : 'cameras'} configured` : undefined}
          action={
            <Link to="/app/cameras" className="flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50">
              Manage <IconArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          }
        >
          {edgeCameras.length === 0 ? (
            <EmptyState title="Cameras will appear here once the Edge runtime is connected" />
          ) : (
            <div className="flex flex-wrap gap-2">
              <Badge tone={problematicCams.length === 0 ? 'green' : 'amber'}>
                {problematicCams.length === 0
                  ? `${healthyCams.length} ${healthyCams.length === 1 ? 'camera' : 'cameras'} working`
                  : `${problematicCams.length} ${problematicCams.length === 1 ? 'camera' : 'cameras'} need attention`}
              </Badge>
              <Badge tone="gray">All data stays on this computer</Badge>
            </div>
          )}
        </Card>

        <Card title="Recent receipts" subtitle="Latest stock received">
          <RecentBatches batches={batches} />
        </Card>
      </div>
    </div>
  )
}

function Kpi({
  label,
  value,
  hint,
  icon,
  tone = 'default',
}: {
  label: string
  value: string
  hint?: string
  icon: ReactNode
  tone?: 'default' | 'brand' | 'warning' | 'danger' | 'positive'
}) {
  const toneClass =
    tone === 'brand'
      ? 'text-brand-700'
      : tone === 'warning'
        ? 'text-amber-600'
        : tone === 'danger'
          ? 'text-red-600'
          : tone === 'positive'
            ? 'text-emerald-600'
            : 'text-gray-900'

  const iconClass =
    tone === 'brand'
      ? 'bg-brand-50 text-brand-600 ring-brand-200/60'
      : tone === 'warning'
        ? 'bg-amber-50 text-amber-600 ring-amber-200/60'
        : tone === 'danger'
          ? 'bg-red-50 text-red-600 ring-red-200/60'
          : tone === 'positive'
            ? 'bg-emerald-50 text-emerald-600 ring-emerald-200/60'
            : 'bg-gray-50 text-gray-600 ring-gray-200/60'

  return (
    <div className="card card-hover p-4 group transition-all duration-200">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-[11px] font-semibold uppercase tracking-wider text-gray-500">{label}</p>
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset transition-transform duration-200 group-hover:scale-105 ${iconClass}`}>
          {icon}
        </span>
      </div>
      <p className={`mt-2 truncate text-xl font-bold tracking-tight tabular ${toneClass}`}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-gray-500">{hint}</p>}
    </div>
  )
}

function ActivityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-gray-500">{label}</dt>
      <dd className="font-semibold text-gray-900">{value}</dd>
    </div>
  )
}

function RecentBatches({ batches }: { batches: Batch[] }) {
  const recent = batches.slice().sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5)
  if (recent.length === 0) return <EmptyState title={EMPTY_COPY.receipts} hint="Received stock shows up here." />
  return (
    <ul className="divide-y divide-gray-100">
      {recent.map((b) => {
        const exp = b.expiry_date ? expiryLabel(daysUntil(b.expiry_date)) : null
        return (
          <li key={b.id} className="flex items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-gray-900">{b.batch_number ?? 'Stock received'}</p>
              <p className="text-xs text-gray-500">{b.quantity} units · {new Date(b.created_at).toLocaleDateString()}</p>
            </div>
            {exp && <Badge tone={exp.tone}>{exp.label}</Badge>}
          </li>
        )
      })}
    </ul>
  )
}