import React, { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, Modal } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { productApi } from '../lib/api/products'
import { storeApi } from '../lib/api/zone'
import { IconTag } from '../components/ui/icons'
import type { Product } from '../lib/api/types'

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

export function ProductsPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<unknown>(null)
  const [sku, setSku] = useState('')
  const [name, setName] = useState('')
  const [brand, setBrand] = useState('')
  const [category, setCategory] = useState('')
  const [unit, setUnit] = useState('unit')
  const [sellingPrice, setSellingPrice] = useState('')
  const [costPrice, setCostPrice] = useState('')
  const [taxRate, setTaxRate] = useState('')

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
      const res = await productApi.list(sid ? { store_id: sid } : undefined)
      setProducts(res.items)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!storeId) return
    setBusy(true)
    setFormError(null)
    try {
      await productApi.create({
        store_id: storeId,
        sku: sku.trim(),
        name: name.trim(),
        brand: brand.trim() || null,
        category: category.trim() || null,
        unit: unit || 'unit',
        selling_price: (Number(sellingPrice || 0)).toFixed(2),
        cost_price: costPrice ? (Number(costPrice)).toFixed(2) : null,
        tax_rate: (Number(taxRate || 0) / 100).toString(),
        is_active: true,
      })
      setCreateOpen(false)
      setSku(''); setName(''); setBrand(''); setCategory(''); setUnit('unit')
      setSellingPrice(''); setCostPrice(''); setTaxRate('')
      await load()
    } catch (err) {
      setFormError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="rounded-lg bg-gray-100 p-1.5">
              <IconTag className="h-4 w-4 text-brand-600" />
            </span>
            <h1 className="font-bold">Products</h1>
          </div>
          <p className="mt-0.5 text-sm text-black">
            Catalogue of SKUs. Products are sold manually via POS/billing; AI
            observations reference them but never change their prices.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} disabled={!storeId}>
          + Add product
        </Button>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading products…" />
      ) : (
        <Card title="Product catalogue" subtitle={`${products.length} product(s)`}>
          {products.length === 0 ? (
            <EmptyState
              title="No products yet"
              hint="Create your first product to start managing catalogue and pricing."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table-base w-full min-w-[720px] text-left">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th>Name</th>
                    <th>SKU</th>
                    <th>Brand</th>
                    <th>Category</th>
                    <th>Cost</th>
                    <th>Selling</th>
                    <th>Tax</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {products.map((p) => (
                    <tr key={p.id} className="hover:bg-gray-50">
                      <td className="font-medium text-gray-800">{p.name}</td>
                      <td className="text-gray-500">{p.sku}</td>
                      <td className="text-gray-500">{p.brand ?? '—'}</td>
                      <td className="text-gray-500">{p.category ?? '—'}</td>
                      <td className="text-gray-500">
                        {p.cost_price != null ? `₹${Number(p.cost_price).toFixed(2)}` : '—'}
                      </td>
                      <td className="font-semibold text-gray-700">
                        ₹{Number(p.selling_price).toFixed(2)}
                      </td>
                      <td className="text-gray-500">{Number(p.tax_rate) * 100}%</td>
                      <td>
                        <Badge tone={p.is_active ? 'green' : 'gray'}>
                          {p.is_active ? 'ACTIVE' : 'DISABLED'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Add product">
        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Name *</span>
            <input required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">SKU *</span>
            <input required value={sku} onChange={(e) => setSku(e.target.value)} className={inputCls} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Brand</span>
              <input value={brand} onChange={(e) => setBrand(e.target.value)} className={inputCls} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Category</span>
              <input value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls} />
            </label>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Selling ₹</span>
              <input type="number" step="0.01" min="0" value={sellingPrice} onChange={(e) => setSellingPrice(e.target.value)} className={inputCls} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Cost ₹</span>
              <input type="number" step="0.01" min="0" value={costPrice} onChange={(e) => setCostPrice(e.target.value)} className={inputCls} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-600">Tax %</span>
              <input type="number" step="0.01" min="0" max="1" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} className={inputCls} placeholder="0.18 = 18%" />
            </label>
          </div>
          {formError ? <ErrorMessage error={formError} compact /> : null}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? 'Saving…' : 'Add product'}
          </Button>
        </form>
      </Modal>
    </div>
  )
}