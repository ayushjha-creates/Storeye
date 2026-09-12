import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, Modal } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { billApi } from '../lib/api/bills'
import { productApi } from '../lib/api/products'
import { customerApi } from '../lib/api/customers'
import { storeApi } from '../lib/api/zone'
import { cleanName } from '../lib/cleanNames'
import type { Bill, Customer, Product } from '../lib/api/types'

interface LineItem {
  product: Product
  quantity: number
  unit_price: number
  tax: number
  line_total: number
}

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

export function BillingPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [bills, setBills] = useState<Bill[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<unknown>(null)

  const [billNumber, setBillNumber] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [lines, setLines] = useState<LineItem[]>([])

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
      const [billsRes, prodRes, custRes] = await Promise.all([
        billApi.list(sid ? { store_id: sid } : undefined),
        productApi.list(sid ? { store_id: sid } : undefined),
        customerApi.list(sid ? { store_id: sid } : undefined),
      ])
      setBills(billsRes.items)
      setProducts(prodRes.items)
      setCustomers(custRes.items)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const totals = useMemo(() => {
    const subtotal = lines.reduce((acc, l) => acc + l.line_total, 0)
    const taxTotal = lines.reduce((acc, l) => acc + l.tax * l.quantity, 0)
    return { subtotal, taxTotal, total: subtotal + taxTotal }
  }, [lines])

  const addLine = () => {
    const product = products.find((p) => p.is_active && p.id !== lines.find((l) => l.product.id === p.id)?.product.id) ?? products.find((p) => p.is_active)
    if (!product) return
    setLines((prev) => [
      ...prev,
      {
        product,
        quantity: 1,
        unit_price: Number(product.selling_price),
        tax: Number(product.tax_rate) * Number(product.selling_price),
        line_total: Number(product.selling_price) * 1,
      },
    ])
  }

  const updateLine = (index: number, patch: Partial<LineItem>) => {
    setLines((prev) =>
      prev.map((l, i) => {
        if (i !== index) return l
        const next = { ...l, ...patch }
        next.line_total = next.unit_price * next.quantity
        next.tax = Number(next.product.tax_rate) * next.unit_price
        return next
      }),
    )
  }

  const removeLine = (index: number) => {
    setLines((prev) => prev.filter((_, i) => i !== index))
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!storeId || lines.length === 0) return
    setBusy(true)
    setFormError(null)
    try {
      await billApi.create({
        store_id: storeId,
        bill_number: billNumber.trim() || `BILL-${Date.now().toString().slice(-6)}`,
        customer_id: customerId || null,
        subtotal: Number(totals.subtotal.toFixed(2)),
        tax_total: Number(totals.taxTotal.toFixed(2)),
        total: Number(totals.total.toFixed(2)),
        delivery_status: 'DRAFT',
        items: lines.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity,
          unit_price: Number(l.unit_price.toFixed(2)),
          tax: Number(l.tax.toFixed(2)),
          line_total: Number(l.line_total.toFixed(2)),
        })),
      })
      setCreateOpen(false)
      setLines([])
      setBillNumber('')
      setCustomerId('')
      await load()
    } catch (err) {
      setFormError(err)
    } finally {
      setBusy(false)
    }
  }

  const customerName = (cid: string | null) =>
    customers.find((c) => c.id === cid)?.name ?? (cid ? (customers.find((c) => c.id === cid)?.mobile ?? cid.slice(0, 8)) : 'Walk-in')

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-bold">Billing</h1>
          <p className="mt-0.5 text-sm text-gray-500">
            Manual billing only — the shopkeeper creates each bill. There is no
            AI-generated billing, and a bill never auto-changes inventory.
          </p>
        </div>
        <Button onClick={() => { setCreateOpen(true); if (lines.length === 0 && products.length > 0) addLine() }} disabled={!storeId}>
          + New bill
        </Button>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading billing…" />
      ) : (
        <Card title="Bills" subtitle={`${bills.length} bill(s)`}>
          {bills.length === 0 ? (
            <EmptyState title="No bills yet" hint="Create a manual bill to start recording transactions." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table-base min-w-[760px] w-full text-left">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th>Bill</th>
                    <th>Customer</th>
                    <th>Items</th>
                    <th>Subtotal</th>
                    <th>Tax</th>
                    <th>Total</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {bills.map((b) => (
                    <tr key={b.id} className="hover:bg-gray-50">
                      <td className="font-mono text-xs font-medium text-brand-700">{cleanName(b.bill_number)}</td>
                      <td className="text-gray-500">{customerName(b.customer_id)}</td>
                      <td className="tabular text-gray-700">{b.items.length}</td>
                      <td className="tabular text-gray-500">₹{Number(b.subtotal).toFixed(2)}</td>
                      <td className="tabular text-gray-500">₹{Number(b.tax_total).toFixed(2)}</td>
                      <td className="font-semibold tabular text-gray-900">₹{Number(b.total).toFixed(2)}</td>
                      <td>
                        <Badge tone={b.delivery_status === 'DELIVERED' ? 'green' : b.delivery_status === 'DRAFT' ? 'gray' : 'blue'}>
                          {b.delivery_status}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap text-gray-400">
                        {new Date(b.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create manual bill">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Bill number</span>
              <input value={billNumber} onChange={(e) => setBillNumber(e.target.value)} className={inputCls} placeholder="auto-generated if blank" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Customer</span>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={inputCls}>
                <option value="">Walk-in</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name ?? c.mobile}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-500">Line items</p>
              <button type="button" onClick={addLine} className="text-xs font-medium text-brand-700 hover:underline">
                + Add product
              </button>
            </div>
            {lines.length === 0 ? (
              <p className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-400">
                No items yet — add a product to build the bill.
              </p>
            ) : (
              <div className="space-y-2">
                {lines.map((l, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <select
                      value={l.product.id}
                      onChange={(e) => {
                        const p = products.find((x) => x.id === e.target.value)
                        if (p) updateLine(i, { product: p, unit_price: Number(p.selling_price) })
                      }}
                      className={`${inputCls} !w-auto flex-1`}
                    >
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} — ₹{Number(p.selling_price).toFixed(2)}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={l.quantity}
                      onChange={(e) => updateLine(i, { quantity: Math.max(1, Number(e.target.value)) })}
                      className={`${inputCls} !w-20`}
                      title="Quantity"
                    />
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={l.unit_price}
                      onChange={(e) => updateLine(i, { unit_price: Number(e.target.value) })}
                      className={`${inputCls} !w-24`}
                      title="Unit price"
                    />
                    <span className="w-24 text-right text-sm text-gray-600">₹{l.line_total.toFixed(2)}</span>
                    <button type="button" onClick={() => removeLine(i)} className="text-gray-400 hover:text-red-600" title="Remove">
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-1 rounded-lg bg-gray-50 p-3 text-sm">
            <p className="flex justify-between"><span className="text-gray-500">Subtotal</span><span>₹{totals.subtotal.toFixed(2)}</span></p>
            <p className="flex justify-between"><span className="text-gray-500">Tax</span><span>₹{totals.taxTotal.toFixed(2)}</span></p>
            <p className="flex justify-between font-bold text-gray-900"><span>Total</span><span>₹{totals.total.toFixed(2)}</span></p>
          </div>

          {formError ? <ErrorMessage error={formError} compact /> : null}
          <Button type="submit" disabled={busy || lines.length === 0} className="w-full">
            {busy ? 'Saving…' : 'Save bill'}
          </Button>
        </form>
      </Modal>
    </div>
  )
}