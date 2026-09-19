import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, Modal } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { productApi } from '../lib/api/products'
import { inventoryApi } from '../lib/api/inventory'
import { storeApi } from '../lib/api/zone'
import { stockStatus, EMPTY_COPY } from '../lib/shop'
import type {
  Batch,
  Inventory,
  InventoryMovement,
  Product,
} from '../lib/api/types'

const EXPIRY_WARNING_DAYS = 30
const DAY_MS = 86_400_000
function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / DAY_MS)
}

type StockFilter = 'ALL' | 'LOW' | 'OUT' | 'EXPIRING'

interface ProductDetail {
  product: Product
  inventory: Inventory | null
  batches: Batch[]
  movements: InventoryMovement[]
}

export function InventoryPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [details, setDetails] = useState<Record<string, ProductDetail>>({})
  const [allBatches, setAllBatches] = useState<Batch[]>([])
  const [filter, setFilter] = useState<StockFilter>('ALL')
  const [activeTab, setActiveTab] = useState<'PRODUCTS' | 'WATCHLIST'>('PRODUCTS')
  const [selected, setSelected] = useState<Product | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [receiveOpen, setReceiveOpen] = useState(false)
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<unknown>(null)

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
      setStoreId(sid)
      const [prodRes, batchRes] = await Promise.all([
        productApi.list(sid ? { store_id: sid } : undefined),
        sid ? inventoryApi.listAllBatches({ store_id: sid }) : Promise.resolve({ items: [] as Batch[] }),
      ])
      setProducts(prodRes.items)
      setAllBatches(batchRes.items ?? [])
      if (sid) {
        const map: Record<string, ProductDetail> = {}
        // Fetch detail for first 30 products to bound requests.
        await Promise.all(
          prodRes.items.slice(0, 30).map(async (p) => {
            try {
              const [inv, batches, movements] = await Promise.all([
                inventoryApi.getProductInventory(sid as string, p.id),
                inventoryApi.listProductBatches(sid as string, p.id),
                inventoryApi.listMovements(sid as string, p.id),
              ])
              map[p.id] = {
                product: p,
                inventory: inv.quantity > 0 || inv.reorder_level > 0 ? inv : null,
                batches: batches.items,
                movements: movements.items,
              }
            } catch {
              map[p.id] = { product: p, inventory: null, batches: [], movements: [] }
            }
          }),
        )
        setDetails(map)
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

  const stockOf = (pid: string) => details[pid]?.inventory?.quantity ?? 0

  const after = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setFormError(null)
    try {
      await fn()
      setReceiveOpen(false)
      setAdjustOpen(false)
      setBatchOpen(false)
      await load()
    } catch (err) {
      setFormError(err)
    } finally {
      setBusy(false)
    }
  }

  const detail = selected ? details[selected.id] : null

  const expiryFor = (pid: string): number | null => {
    const days = (allBatches ?? [])
      .filter((b) => b.product_id === pid && b.expiry_date)
      .map((b) => daysUntil(b.expiry_date as string))
    return days.length > 0 ? Math.min(...days) : null
  }

  // Detailed stock & valuation analysis
  const totalUnits = products.reduce((acc, p) => acc + stockOf(p.id), 0)
  const totalStockValue = products.reduce((acc, p) => {
    const qty = stockOf(p.id)
    const price = Number(p.selling_price || 0)
    return acc + qty * price
  }, 0)

  // Batch-level countdown and risk classification
  const batchRisks = (allBatches ?? [])
    .filter((b) => b.quantity > 0 && b.expiry_date)
    .map((b) => {
      const prod = products.find((p) => p.id === b.product_id)
      const days = daysUntil(b.expiry_date as string)
      const unitVal = Number(b.mrp ?? prod?.selling_price ?? 0)
      const riskValue = b.quantity * unitVal
      let urgency: 'EXPIRED' | 'URGENT' | 'NEAR' | 'HEALTHY' = 'HEALTHY'
      if (days <= 0) urgency = 'EXPIRED'
      else if (days <= 7) urgency = 'URGENT'
      else if (days <= 30) urgency = 'NEAR'
      return {
        batch: b,
        product: prod,
        days,
        riskValue,
        urgency,
      }
    })
    .sort((a, b) => a.days - b.days)

  const expiredBatches = batchRisks.filter((r) => r.urgency === 'EXPIRED')
  const urgentBatches = batchRisks.filter((r) => r.urgency === 'URGENT')
  const nearBatches = batchRisks.filter((r) => r.urgency === 'NEAR')

  const expiredValue = expiredBatches.reduce((acc, r) => acc + r.riskValue, 0)
  const urgentValue = urgentBatches.reduce((acc, r) => acc + r.riskValue, 0)
  const nearValue = nearBatches.reduce((acc, r) => acc + r.riskValue, 0)

  const lowStockCount = products.filter((p) => {
    const inv = details[p.id]?.inventory
    const qty = inv?.quantity ?? 0
    const reorder = inv?.reorder_level ?? 0
    return qty > 0 && qty <= Math.max(reorder, 1)
  }).length

  const outOfStockCount = products.filter((p) => stockOf(p.id) === 0).length

  const filteredProducts = products.filter((p) => {
    if (filter === 'ALL') return true
    const inv = details[p.id]?.inventory
    const qty = inv?.quantity ?? 0
    const reorder = inv?.reorder_level ?? 0
    if (filter === 'OUT') return qty <= 0
    if (filter === 'LOW') return qty > 0 && qty <= Math.max(reorder, 1)
    if (filter === 'EXPIRING') {
      const d = expiryFor(p.id)
      return d != null && d <= EXPIRY_WARNING_DAYS
    }
    return true
  })

  const filters: { key: StockFilter; label: string }[] = [
    { key: 'ALL', label: 'All' },
    { key: 'LOW', label: 'Running low' },
    { key: 'OUT', label: 'Out of stock' },
    { key: 'EXPIRING', label: 'Expiring soon' },
  ]

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-bold">Stock & Inventory Intelligence</h1>
          <p className="mt-0.5 text-sm text-black">
            Real-time stock levels, inventory valuation, and batch expiry risk tracking.{' '}
            <Link to="/app/products" className="text-brand-600 underline decoration-brand-200 hover:text-brand-700">
              Manage products →
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/app/receive">
            <Button kind="primary">+ Receive Stock</Button>
          </Link>
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading stock intelligence…" />
      ) : (
        <>
          {/* Top Stock & Expiry KPI Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-gray-700">Total Stock Value</p>
              <p className="mt-2 text-2xl font-bold text-gray-900">
                ₹{totalStockValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </p>
              <p className="mt-1 text-xs text-gray-700">
                {totalUnits} units across {products.length} SKUs
              </p>
            </div>

            <div
              onClick={() => { setActiveTab('WATCHLIST'); setFilter('ALL') }}
              className={`cursor-pointer rounded-xl border p-4 shadow-sm transition hover:shadow-md ${
                expiredBatches.length > 0
                  ? 'border-red-300 bg-red-50/50'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wider text-red-700">🚨 Expired</p>
                {expiredBatches.length > 0 && <Badge tone="red">{expiredBatches.length}</Badge>}
              </div>
              <p className="mt-2 text-2xl font-bold text-red-700">
                ₹{expiredValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </p>
              <p className="mt-1 text-xs text-red-600 font-medium">
                {expiredBatches.length > 0 ? 'Immediate discard / vendor credit' : 'No expired batches'}
              </p>
            </div>

            <div
              onClick={() => { setActiveTab('WATCHLIST'); setFilter('ALL') }}
              className={`cursor-pointer rounded-xl border p-4 shadow-sm transition hover:shadow-md ${
                urgentBatches.length > 0
                  ? 'border-amber-300 bg-amber-50/50'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">⚠️ Urgent (&lt; 7 Days)</p>
                {urgentBatches.length > 0 && <Badge tone="amber">{urgentBatches.length}</Badge>}
              </div>
              <p className="mt-2 text-2xl font-bold text-amber-700">
                ₹{urgentValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </p>
              <p className="mt-1 text-xs text-amber-600 font-medium">
                {urgentBatches.length > 0 ? 'Clearance discount recommended' : 'None expiring this week'}
              </p>
            </div>

            <div
              onClick={() => { setActiveTab('WATCHLIST'); setFilter('ALL') }}
              className="cursor-pointer rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition hover:shadow-md"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-700">🟡 Near (&lt; 30 Days)</p>
                {nearBatches.length > 0 && <Badge tone="amber">{nearBatches.length}</Badge>}
              </div>
              <p className="mt-2 text-2xl font-bold text-gray-900">
                ₹{nearValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </p>
              <p className="mt-1 text-xs text-gray-700">
                {nearBatches.length > 0 ? 'Prioritize on front shelf (FIFO)' : 'Stock fresh for 30+ days'}
              </p>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-gray-700">Stock Replenishment</p>
              <p className="mt-2 text-2xl font-bold text-gray-900">
                {outOfStockCount > 0 ? (
                  <span className="text-red-600">{outOfStockCount} Out</span>
                ) : (
                  <span className="text-emerald-700">0 Out</span>
                )}
                <span className="text-gray-400 font-normal mx-1">/</span>
                <span className={lowStockCount > 0 ? 'text-amber-600' : 'text-gray-700'}>
                  {lowStockCount} Low
                </span>
              </p>
              <p className="mt-1 text-xs text-gray-700">Items below reorder point</p>
            </div>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center border-b border-gray-200">
            <button
              onClick={() => setActiveTab('PRODUCTS')}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition ${
                activeTab === 'PRODUCTS'
                  ? 'border-brand-600 text-brand-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              All Products ({products.length})
            </button>
            <button
              onClick={() => setActiveTab('WATCHLIST')}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition ${
                activeTab === 'WATCHLIST'
                  ? 'border-brand-600 text-brand-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <span>🚨 Expiry Risk Watchlist</span>
              {expiredBatches.length + urgentBatches.length > 0 && (
                <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-xs font-bold text-red-700">
                  {expiredBatches.length + urgentBatches.length}
                </span>
              )}
            </button>
          </div>

          {activeTab === 'PRODUCTS' ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {filters.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                      filter === f.key
                        ? 'bg-brand-700 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <Card title="Products" subtitle={`${filteredProducts.length} of ${products.length} SKU(s)`}>
                {products.length === 0 ? (
                  <EmptyState title="No products yet" hint="Add your first product on the Products page." />
                ) : filteredProducts.length === 0 ? (
                  <EmptyState title="Nothing to show here" hint={EMPTY_COPY.stock} />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table-base min-w-[640px] w-full text-left">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th>Product</th>
                          <th>SKU</th>
                          <th>Stock</th>
                          <th>Value</th>
                          <th>Status</th>
                          <th>Expiry Countdown</th>
                          <th className="text-right"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {filteredProducts.map((p) => {
                          const inv = details[p.id]?.inventory
                          const qty = inv?.quantity ?? 0
                          const reorder = inv?.reorder_level ?? 0
                          const status = stockStatus(qty, reorder)
                          const expDays = expiryFor(p.id)
                          const stockVal = qty * Number(p.selling_price || 0)
                          return (
                            <tr key={p.id} className="hover:bg-gray-50">
                              <td className="font-medium text-gray-800">{p.name}</td>
                              <td className="text-gray-500">{p.sku}</td>
                              <td>
                                <Badge tone={qty === 0 ? 'red' : qty <= Math.max(reorder, 1) ? 'amber' : 'green'}>
                                  {qty}
                                </Badge>
                              </td>
                              <td className="text-gray-700 font-medium text-sm">
                                ₹{stockVal.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                              </td>
                              <td>
                                <span className="text-sm text-gray-700">
                                  {status.icon} {status.label}
                                </span>
                              </td>
                              <td>
                                {expDays != null ? (
                                  expDays <= 0 ? (
                                    <Badge tone="red">Expired {Math.abs(expDays)}d ago</Badge>
                                  ) : expDays <= 7 ? (
                                    <Badge tone="red">{expDays}d left (Urgent)</Badge>
                                  ) : expDays <= 30 ? (
                                    <Badge tone="amber">{expDays}d left</Badge>
                                  ) : (
                                    <Badge tone="green">{Math.round(expDays / 30)} mos fresh</Badge>
                                  )
                                ) : (
                                  <span className="text-gray-400">—</span>
                                )}
                              </td>
                              <td className="text-right">
                                <Button
                                  kind="ghost"
                                  onClick={() => setSelected(p)}
                                  className="!px-2 !py-1"
                                  title="View stock, batches and movements"
                                >
                                  Details
                                </Button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          ) : (
            /* Expiry Risk Watchlist View */
            <Card
              title="Batch Expiry Risk Watchlist"
              subtitle={`${batchRisks.length} active batch(es) tracked with expiry dates (sorted by urgency)`}
            >
              {batchRisks.length === 0 ? (
                <EmptyState
                  title="No active batches tracked"
                  hint="Receive stock using Smart Intake to automatically track batch expiry countdowns."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table-base min-w-[720px] w-full text-left">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th>Product</th>
                        <th>Batch</th>
                        <th>Units</th>
                        <th>Expiry Date</th>
                        <th>Countdown</th>
                        <th>Value at Risk</th>
                        <th>Action Advice</th>
                        <th className="text-right"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {batchRisks.map(({ batch: b, product: prod, days, riskValue, urgency }) => {
                        return (
                          <tr key={b.id} className="hover:bg-gray-50">
                            <td>
                              <p className="font-medium text-gray-900">{prod?.name ?? 'Unknown Product'}</p>
                              <p className="text-xs text-gray-400">{prod?.sku ?? '—'}</p>
                            </td>
                            <td className="font-mono text-sm text-gray-700">{b.batch_number ?? '—'}</td>
                            <td>
                              <span className="font-semibold text-gray-800">{b.quantity}</span>
                            </td>
                            <td className="text-gray-600 text-sm">
                              {b.expiry_date ? String(b.expiry_date) : '—'}
                            </td>
                            <td>
                              {days <= 0 ? (
                                <Badge tone="red">Expired {Math.abs(days)}d ago</Badge>
                              ) : days <= 7 ? (
                                <Badge tone="red">{days} day(s) left</Badge>
                              ) : days <= 30 ? (
                                <Badge tone="amber">{days} day(s) left</Badge>
                              ) : (
                                <Badge tone="green">{days} days ({Math.round(days / 30)} mos)</Badge>
                              )}
                            </td>
                            <td className="font-semibold text-gray-900 text-sm">
                              ₹{riskValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                            </td>
                            <td>
                              {urgency === 'EXPIRED' ? (
                                <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold bg-red-100 text-red-800">
                                  Dispose / Claim Credit
                                </span>
                              ) : urgency === 'URGENT' ? (
                                <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold bg-amber-100 text-amber-800">
                                  Flash 50% Off / Clear
                                </span>
                              ) : urgency === 'NEAR' ? (
                                <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold bg-blue-100 text-blue-800">
                                  Front Shelf (FIFO)
                                </span>
                              ) : (
                                <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold bg-emerald-100 text-emerald-800">
                                  Healthy Stock
                                </span>
                              )}
                            </td>
                            <td className="text-right">
                              {prod && (
                                <Button
                                  kind="ghost"
                                  onClick={() => setSelected(prod)}
                                  className="!px-2 !py-1"
                                >
                                  Details
                                </Button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}

          {selected && detail && (
            <Card
              title={`${selected.name} — Stock Details`}
              subtitle={selected.sku}
              action={
                <div className="flex flex-wrap gap-2">
                  <Button kind="primary" onClick={() => { setReceiveOpen(true); setAdjustOpen(false); setBatchOpen(false) }}>
                    + Receive stock
                  </Button>
                  <Button kind="secondary" onClick={() => { setAdjustOpen(true); setReceiveOpen(false); setBatchOpen(false) }}>
                    Adjust
                  </Button>
                  <Button kind="secondary" onClick={() => { setBatchOpen(true); setReceiveOpen(false); setAdjustOpen(false) }}>
                    New batch
                  </Button>
                </div>
              }
            >
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                    Current stock
                  </p>
                  <div className="flex items-center gap-4">
                    <p className="text-3xl font-bold text-gray-900">
                      {stockOf(selected.id)}
                    </p>
                    <Badge tone={stockOf(selected.id) === 0 ? 'red' : 'green'}>
                      {stockOf(selected.id) === 0 ? 'OUT OF STOCK' : 'IN STOCK'}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-gray-400">
                    Reorder level: {detail.inventory?.reorder_level ?? 0} · Reorder qty:{' '}
                    {detail.inventory?.reorder_quantity ?? 0}
                  </p>

                  <p className="mt-6 text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                    Batches ({detail.batches.length})
                  </p>
                  {detail.batches.length === 0 ? (
                    <p className="text-sm text-gray-400">No batches for this product.</p>
                  ) : (
                    <div className="overflow-hidden rounded-lg border border-gray-100">
                      <table className="table-base w-full text-left">
                        <thead>
                          <tr className="border-b border-gray-100">
                            <th>Batch</th>
                            <th>Expiry</th>
                            <th>MRP</th>
                            <th>Qty</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                          {detail.batches.map((b) => (
                            <tr key={b.id}>
                              <td className="text-gray-700">{b.batch_number ?? '—'}</td>
                              <td className="text-gray-500">{b.expiry_date ?? '—'}</td>
                              <td className="text-gray-500">
                                {b.mrp != null ? `₹${Number(b.mrp).toFixed(2)}` : '—'}
                              </td>
                              <td className="text-gray-500">{b.quantity}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                    Movement history ({detail.movements.length})
                  </p>
                  {detail.movements.length === 0 ? (
                    <p className="text-sm text-gray-400">No movements recorded.</p>
                  ) : (
                    <div className="max-h-72 overflow-y-auto rounded-lg border border-gray-100">
                      <table className="table-base w-full text-left">
                        <thead className="sticky top-0 border-b border-gray-100 bg-gray-50">
                          <tr>
                            <th>Time</th>
                            <th>Type</th>
                            <th>Change</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                          {detail.movements.map((m) => (
                            <tr key={m.id}>
                              <td className="whitespace-nowrap text-gray-500">
                                {new Date(m.timestamp_utc).toLocaleString()}
                              </td>
                              <td>
                                <Badge tone={m.movement_type === 'PURCHASE' ? 'green' : m.movement_type === 'ADJUSTMENT' ? 'amber' : 'blue'}>
                                  {m.movement_type}
                                </Badge>
                              </td>
                              <td className={`font-medium ${m.quantity_change >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                                {m.quantity_change >= 0 ? `+${m.quantity_change}` : m.quantity_change}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}
        </>
      )}

      {/* Receive stock modal */}
      <Modal open={receiveOpen} onClose={() => setReceiveOpen(false)} title={`Receive stock — ${selected?.name ?? ''}`}>
        <ReceiveForm
          storeId={storeId}
          productId={selected?.id}
          busy={busy}
          error={formError}
          onSubmit={(data) => after(() => inventoryApi.receive(data))}
        />
      </Modal>

      {/* Adjust stock modal */}
      <Modal open={adjustOpen} onClose={() => setAdjustOpen(false)} title={`Adjust stock — ${selected?.name ?? ''}`}>
        <AdjustForm
          storeId={storeId}
          productId={selected?.id}
          busy={busy}
          error={formError}
          onSubmit={(data) => after(() => inventoryApi.adjust(data))}
        />
      </Modal>

      {/* Create batch modal */}
      <Modal open={batchOpen} onClose={() => setBatchOpen(false)} title={`Create batch — ${selected?.name ?? ''}`}>
        <BatchForm
          storeId={storeId}
          productId={selected?.id}
          busy={busy}
          error={formError}
          onSubmit={(data) => after(() => inventoryApi.createBatch(data))}
        />
      </Modal>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  )
}

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

function ReceiveForm({
  storeId,
  productId,
  busy,
  error,
  onSubmit,
}: {
  storeId: string | null
  productId?: string
  busy: boolean
  error: unknown
  onSubmit: (data: { store_id: string; product_id: string; quantity_change: number; reference?: string | null }) => void
}) {
  const [qty, setQty] = useState(10)
  const [ref, setRef] = useState('')
  if (!storeId || !productId) return null
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({ store_id: storeId, product_id: productId, quantity_change: Number(qty), reference: ref || null })
      }}
    >
      <Field label="Quantity to receive">
        <input type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value))} className={inputCls} required />
      </Field>
      <Field label="Reference (optional)">
        <input value={ref} onChange={(e) => setRef(e.target.value)} className={inputCls} placeholder="e.g. supplier invoice" />
      </Field>
      {error ? <ErrorMessage error={error} compact /> : null}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Saving…' : 'Receive stock'}</Button>
    </form>
  )
}

function AdjustForm({
  storeId,
  productId,
  busy,
  error,
  onSubmit,
}: {
  storeId: string | null
  productId?: string
  busy: boolean
  error: unknown
  onSubmit: (data: { store_id: string; product_id: string; quantity_change: number; reference?: string | null; require_sufficient_stock: boolean }) => void
}) {
  const [qty, setQty] = useState(-1)
  const [ref, setRef] = useState('')
  const [strict, setStrict] = useState(true)
  if (!storeId || !productId) return null
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({ store_id: storeId, product_id: productId, quantity_change: Number(qty), reference: ref || null, require_sufficient_stock: strict })
      }}
    >
      <p className="text-xs text-gray-500">
        Negative reduces stock (write-off/damage). Positive adds stock.
      </p>
      <Field label="Signed adjustment">
        <input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} className={inputCls} required />
      </Field>
      <Field label="Reference (optional)">
        <input value={ref} onChange={(e) => setRef(e.target.value)} className={inputCls} placeholder="e.g. damaged goods" />
      </Field>
      <label className="flex items-center gap-2 text-xs text-gray-600">
        <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} className="h-3.5 w-3.5" />
        Prevent stock going negative (require sufficient stock)
      </label>
      {error ? <ErrorMessage error={error} compact /> : null}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Saving…' : 'Apply adjustment'}</Button>
    </form>
  )
}

function BatchForm({
  storeId,
  productId,
  busy,
  error,
  onSubmit,
}: {
  storeId: string | null
  productId?: string
  busy: boolean
  error: unknown
  onSubmit: (data: { store_id: string; product_id: string; batch_number?: string | null; manufacturing_date?: string | null; expiry_date?: string | null; mrp?: number | null }) => void
}) {
  const [batchNumber, setBatchNumber] = useState('')
  const [expiry, setExpiry] = useState('')
  const [mrp, setMrp] = useState('')
  if (!storeId || !productId) return null
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({
          store_id: storeId,
          product_id: productId,
          batch_number: batchNumber || null,
          manufacturing_date: null,
          expiry_date: expiry || null,
          mrp: mrp ? Number(mrp) : null,
        })
      }}
    >
      <Field label="Batch number (optional)">
        <input value={batchNumber} onChange={(e) => setBatchNumber(e.target.value)} className={inputCls} placeholder="e.g. LOT-2026-01" />
      </Field>
      <Field label="Expiry date (optional)">
        <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} className={inputCls} />
      </Field>
      <Field label="MRP (optional)">
        <input type="number" step="0.01" min="0" value={mrp} onChange={(e) => setMrp(e.target.value)} className={inputCls} placeholder="e.g. 150" />
      </Field>
      {error ? <ErrorMessage error={error} compact /> : null}
      <Button type="submit" disabled={busy} className="w-full">{busy ? 'Saving…' : 'Create batch'}</Button>
    </form>
  )
}