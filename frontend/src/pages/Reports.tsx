import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Stat } from '../components/ui/Card'
import { EmptyState, ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { Badge } from '../components/ui/Badge'
import { LineChart, BarChart } from '../components/ui/charts'
import { useEdge } from '../edge/EdgeContext'
import { cleanName } from '../lib/cleanNames'
import { storeApi } from '../lib/api/zone'
import { saleApi } from '../lib/api/sales'
import { billApi } from '../lib/api/bills'
import { productApi } from '../lib/api/products'
import type { Bill, Product, Sale } from '../lib/api/types'
import { IconBox, IconReceipt, IconRupee } from '../components/ui/icons'

const DAY_MS = 86_400_000

function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function buckets(sales: Sale[], days: number): number[] {
  const keys = Array.from({ length: days }, (_, i) => {
    const d = new Date(Date.now() - (days - 1 - i) * DAY_MS)
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
  })
  const map = new Map<string, number>()
  sales.forEach((s) => {
    const k = dayKey(s.sale_timestamp_utc)
    map.set(k, (map.get(k) ?? 0) + Number(s.total))
  })
  return keys.map((k) => map.get(k) ?? 0)
}

function dayLabels(days: number): string[] {
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(Date.now() - (days - 1 - i) * DAY_MS)
    return days > 14 ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : d.toLocaleDateString(undefined, { weekday: 'short' })
  })
}

export function ReportsPage() {
  const { edgeOnline } = useEdge().status
  const [storeName, setStoreName] = useState('')
  const [sales, setSales] = useState<Sale[]>([])
  const [bills, setBills] = useState<Bill[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        if (stores.items[0]) {
          sid = stores.items[0].id
          setStoreName(cleanName(stores.items[0].name))
        }
      } catch {
        // continue
      }
      const [saleRes, billRes, prodRes] = await Promise.all([
        sid ? saleApi.list({ store_id: sid }) : saleApi.list(),
        sid ? billApi.list({ store_id: sid }) : billApi.list(),
        sid ? productApi.list({ store_id: sid }) : productApi.list(),
      ])
      setSales(saleRes.items)
      setBills(billRes.items)
      setProducts(prodRes.items)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const productNameById = new Map(products.map((p) => [p.id, p.name]))

  // 30-day window derived from real sale records.
  const cutoff = Date.now() - 30 * DAY_MS
  const sales30 = sales.filter((s) => new Date(s.sale_timestamp_utc).getTime() >= cutoff)
  const bills30 = bills.filter((b) => new Date(b.created_at).getTime() >= cutoff)
  const revenue30 = sales30.reduce((sum, s) => sum + Number(s.total), 0)
  const units30 = sales30.reduce((sum, s) => sum + s.items.reduce((acc, it) => acc + it.quantity, 0), 0)
  const avgBill = bills30.length > 0 ? revenue30 / Math.max(bills30.length, sales30.length || 1) : 0

  const unitByProduct = new Map<string, number>()
  sales30.forEach((s) => s.items.forEach((it) => unitByProduct.set(it.product_id, (unitByProduct.get(it.product_id) ?? 0) + it.quantity)))
  const topProducts = [...unitByProduct.entries()]
    .map(([id, qty]) => ({ name: productNameById.get(id) ?? id.slice(0, 8), qty }))
    .sort((a, b) => b.qty - a.qty)
    .slice(0, 7)

  const revenue14 = buckets(sales30, 14)
  const hasData = sales.length > 0 || bills.length > 0

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="font-bold">Reports &amp; Analytics</h1>
          </div>
          <p className="mt-0.5 text-sm text-gray-500">
            {storeName || 'Store'} · real billing &amp; sales records · {edgeOnline ? 'live' : 'last known good'}
          </p>
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Preparing reports…" />
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Revenue · 30d"
              value={`₹${revenue30.toLocaleString('en-IN')}`}
              hint={`from ${sales30.length} sale(s)`}
              icon={<IconRupee className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Bills · 30d"
              value={bills30.length}
              hint="invoices created"
              icon={<IconReceipt className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Units sold · 30d"
              value={units30}
              hint="line quantities"
              icon={<IconBox className="h-4 w-4 text-brand-400" />}
              tone="brand"
            />
            <Stat
              label="Avg. bill value"
              value={`₹${avgBill.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
              hint="30-day average"
              icon={<IconRupee className="h-4 w-4 text-gray-500" />}
              tone="default"
            />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Card
              className="xl:col-span-2"
              title="Revenue trend — last 14 days"
              subtitle="Daily billed totals from real sales records"
              action={
                <Link to="/app/billing" className="text-xs font-medium text-brand-700 hover:underline">
                  Billing →
                </Link>
              }
            >
              {!hasData ? (
                <EmptyState title="No sales records yet" hint="Create a bill from the Billing page to populate reports." />
              ) : (
                <>
                  <LineChart values={revenue14} labels={dayLabels(14)} color="#3b82f6" height={160} />
                  <p className="mt-2 text-xs text-gray-400">
                    {sales.length} sale record(s) on file.
                  </p>
                </>
              )}
            </Card>

            <Card title="Top products · 30d" subtitle="Units from sale line items">
              {topProducts.length === 0 ? (
                <EmptyState title="No units sold yet" hint="Sold items by quantity will appear here." />
              ) : (
                <>
                  <BarChart
                    data={topProducts.slice(0, 6).map((p) => ({ label: p.name.slice(0, 8), value: p.qty, sub: String(p.qty) }))}
                    color="#3b82f6"
                    height={160}
                  />
                  <ul className="mt-2 divide-y divide-gray-100">
                    {topProducts.slice(0, 5).map((p) => (
                      <li key={p.name} className="flex items-center justify-between py-1.5 text-sm">
                        <span className="truncate text-gray-700">{p.name}</span>
                        <span className="ml-2 shrink-0 font-semibold tabular text-gray-900">{p.qty}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>
          </div>

          <Card
            title="Recent bills"
            subtitle="Latest invoices from the local store"
            action={
              <Link to="/app/billing" className="text-xs font-medium text-brand-700 hover:underline">
                Open Billing →
              </Link>
            }
          >
            {bills.length === 0 ? (
              <EmptyState title="No bills yet" hint="Bills from the Billing page appear here." />
            ) : (
              <div className="overflow-x-auto">
                <table className="table-base w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th>Bill</th>
                      <th>Date</th>
                      <th>Items</th>
                      <th>Total</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {bills.slice().sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 10).map((b) => (
                      <tr key={b.id}>
                        <td className="font-mono text-xs font-medium text-brand-700">{cleanName(b.bill_number)}</td>
                        <td className="text-gray-500">{new Date(b.created_at).toLocaleDateString()}</td>
                        <td className="tabular text-gray-700">{b.items.reduce((acc, it) => acc + it.quantity, 0)} unit(s)</td>
                        <td className="font-semibold tabular text-gray-900">₹{Number(b.total).toLocaleString('en-IN')}</td>
                        <td>
                          <Badge tone={b.delivery_status === 'DELIVERED' ? 'green' : 'blue'}>{b.delivery_status}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}