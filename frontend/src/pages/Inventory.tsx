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
import type {
  Batch,
  Inventory,
  InventoryMovement,
  Product,
} from '../lib/api/types'

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
      const prodRes = await productApi.list(sid ? { store_id: sid } : undefined)
      setProducts(prodRes.items)
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

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-bold">Inventory</h1>
          <p className="mt-0.5 text-sm text-black">
            Stock is updated ONLY through FastAPI domain services (receive /
            adjust / batch). All mutations are atomic.
          </p>
        </div>
        <Link to="/app/inventory/receive">
          <Button kind="primary">+ Smart Batch Receiving</Button>
        </Link>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading inventory…" />
      ) : (
        <>
          <Card title="Products" subtitle={`${products.length} SKU(s)`}>
            {products.length === 0 ? (
              <EmptyState title="No products yet" hint="Add products via the Products page or the API." />
            ) : (
              <div className="overflow-x-auto">
                <table className="table-base min-w-[640px] w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th>Product</th>
                      <th>SKU</th>
                      <th>Stock</th>
                      <th>Reorder</th>
                      <th>Price</th>
                      <th>Batches</th>
                      <th className="text-right"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {products.map((p) => {
                      const inv = details[p.id]?.inventory
                      const stock = inv?.quantity ?? 0
                      const reorder = inv?.reorder_level ?? 0
                      const batchCount = details[p.id]?.batches?.length ?? 0
                      return (
                        <tr key={p.id} className="hover:bg-gray-50">
                          <td className="font-medium text-gray-800">{p.name}</td>
                          <td className="text-gray-500">{p.sku}</td>
                          <td>
                            <Badge tone={stock <= reorder && reorder > 0 ? 'amber' : stock === 0 ? 'red' : 'green'}>
                              {stock}
                            </Badge>
                          </td>
                          <td className="text-gray-500">{reorder}</td>
                          <td className="text-gray-500">
                            ₹{Number(p.selling_price).toFixed(2)}
                          </td>
                          <td className="text-gray-500">{batchCount}</td>
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