import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Stat } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, Modal } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { intelligenceApi, COMPARISON_STATUS_LABEL } from '../lib/api/intelligence'
import { alertApi, ALERT_TYPE_LABEL } from '../lib/api/alerts'
import { productApi } from '../lib/api/products'
import { storeApi } from '../lib/api/zone'
import { IconSparkle } from '../components/ui/icons'
import type { Alert, Product, ProductIntelligenceRow } from '../lib/api/types'

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

function statusTone(status: string): 'gray' | 'green' | 'amber' | 'red' | 'purple' {
  switch (status) {
    case 'MATCH':
      return 'green'
    case 'POSSIBLE_SHORTAGE':
      return 'red'
    case 'POSSIBLE_SURPLUS':
      return 'amber'
    case 'NO_INVENTORY':
      return 'purple'
    case 'NOT_ASSESSED':
      return 'gray'
    default:
      return 'gray'
  }
}

export function ProductIntelligencePage() {
  const [rows, setRows] = useState<ProductIntelligenceRow[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  // Minimal class->product mapping editor for unmapped classes.
  const [mappingOpen, setMappingOpen] = useState(false)
  const [mappingClass, setMappingClass] = useState('')
  const [mappingProductId, setMappingProductId] = useState('')
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
      if (sid) {
        const [pr, pl] = await Promise.all([
          intelligenceApi.products({ store_id: sid }),
          productApi.list({ store_id: sid }),
        ])
        setRows(pr.items)
        setProducts(pl.items)

        try {
          const alertRes = await alertApi.list({ store_id: sid, status: 'OPEN', limit: 10 })
          setAlerts(alertRes.items)
        } catch {
          setAlerts([]) // related alerts are best effort
        }
      } else {
        setRows([])
        setProducts([])
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

  const unmappedClasses = useMemo(
    () => rows.filter((r) => !r.mapped).map((r) => r.ai_class),
    [rows],
  )

  const relatedAlerts = useMemo(
    () =>
      alerts
        .filter((a) => a.alert_type === 'SHORTAGE' || a.alert_type === 'SURPLUS')
        .slice(0, 5),
    [alerts],
  )

  const stats = useMemo(() => {
    const visible = rows.reduce((sum, r) => sum + (r.visible_count || 0), 0)
    const shortages = rows.filter((r) => r.comparison_status === 'POSSIBLE_SHORTAGE').length
    const surpluses = rows.filter((r) => r.comparison_status === 'POSSIBLE_SURPLUS').length
    return { visible, shortages, surpluses, unmapped: unmappedClasses.length }
  }, [rows, unmappedClasses])

  const openMapping = (aiClass: string) => {
    setMappingClass(aiClass)
    setMappingProductId('')
    setFormError(null)
    setMappingOpen(true)
  }

  const saveMapping = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mappingProductId) return
    setBusy(true)
    setFormError(null)
    try {
      const target = products.find((p) => p.id === mappingProductId)
      if (!target) return
      const current = target.ai_classes ?? []
      const next = current.includes(mappingClass)
        ? current
        : [...current, mappingClass]
      await productApi.update(target.id, { ai_classes: next })
      setMappingOpen(false)
      await load()
    } catch (err) {
      setFormError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-shell space-y-6">
      <div>
        <div className="flex items-center gap-2.5">
          <span className="rounded-lg bg-gray-100 p-1.5">
            <IconSparkle className="h-4 w-4 text-brand-600" />
          </span>
          <h1 className="font-bold">Product Intelligence</h1>
        </div>
        <p className="text-sm text-gray-500">
          What the Edge AI currently sees on shelves vs recorded inventory.
          <span className="font-medium"> Informational only</span> — nothing here ever
          changes stock.
        </p>
      </div>

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

      {error && !loading ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading product intelligence…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="AI visible qty" value={stats.visible} hint="All cameras, 24h" />
            <Stat label="Possible shortages" value={stats.shortages} hint="Fewer visible than recorded" tone={stats.shortages ? 'danger' : 'default'} />
            <Stat label="Possible surpluses" value={stats.surpluses} hint="More visible than recorded" tone={stats.surpluses ? 'warning' : 'default'} />
            <Stat label="Product candidates" value={stats.unmapped} hint="Unknown products to map" tone="brand" />
          </div>

          <Card
            title="Visible vs recorded"
            subtitle="Comparisons are camera-scoped and derived from real observations. ‘Visible quantity’ is an estimate, not true stock."
          >
            {rows.length === 0 ? (
              <EmptyState
                title="No product detections yet"
                hint="Run the Edge AI on a shelf camera with shelf_regions configured, or wait for observations."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="table-base w-full min-w-[840px] text-left">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th>AI class</th>
                      <th>Product</th>
                      <th>Camera</th>
                      <th>Visible</th>
                      <th>DB inventory</th>
                      <th>Difference</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {rows.map((r, idx) => (
                      <tr key={`${r.ai_class}-${r.camera_id ?? idx}`} className="hover:bg-gray-50">
                        <td>
                          <div className="font-medium text-gray-800">{r.ai_class}</div>
                          {!r.mapped && (
                            <button
                              onClick={() => openMapping(r.ai_class)}
                              className="mt-0.5 text-xs font-medium text-brand-600 hover:underline"
                            >
                              Map to product →
                            </button>
                          )}
                        </td>
                        <td>
                          {r.mapped ? (
                            <>
                              <span className="font-medium text-gray-800">{r.product_name}</span>
                              <span className="ml-1 text-gray-400">({r.sku})</span>
                            </>
                          ) : (
                            <Badge tone="purple">Unknown product — map to catalog</Badge>
                          )}
                        </td>
                        <td>{r.camera_name ?? '—'}</td>
                        <td className="font-semibold text-gray-800">{r.visible_count}</td>
                        <td className="text-gray-600">
                          {r.database_quantity ?? '—'}
                        </td>
                        <td>
                          {r.difference == null
                            ? '—'
                            : `${r.difference > 0 ? '+' : ''}${r.difference}`}
                        </td>
                        <td>
                          <Badge tone={statusTone(r.comparison_status)}>
                            {COMPARISON_STATUS_LABEL[r.comparison_status] ?? r.comparison_status}
                          </Badge>
                          {r.message ? (
                            <p className="mt-1 max-w-[260px] text-xs text-gray-400">{r.message}</p>
                          ) : null}
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

      <Modal
        open={mappingOpen}
        onClose={() => setMappingOpen(false)}
        title={`Map “${mappingClass}” to a product`}
      >
        <form onSubmit={saveMapping} className="space-y-3">
          <p className="text-xs text-gray-500">
            Assign this detected AI class to a product through its explicit{' '}
            <code className="rounded bg-gray-100 px-1">ai_classes</code> field. This is the
            only way a class becomes a product — no silent guessing.
          </p>
          <select
            value={mappingProductId}
            onChange={(e) => setMappingProductId(e.target.value)}
            className={inputCls}
          >
            <option value="">Select a product…</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.sku})
              </option>
            ))}
          </select>
          {formError ? <ErrorMessage error={formError} compact /> : null}
          <Button type="submit" disabled={busy || !mappingProductId} className="w-full">
            {busy ? 'Saving…' : 'Map class'}
          </Button>
        </form>
      </Modal>
    </div>
  )
}