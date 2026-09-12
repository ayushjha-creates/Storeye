import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { reconciliationApi } from '../lib/api/reconciliation'
import { productApi } from '../lib/api/products'
import { storeApi } from '../lib/api/zone'
import type { Product, ReconciliationResult } from '../lib/api/types'
import { IconScan } from '../components/ui/icons'

// Reconciliation UI.
//
// CRITICAL: reconciliation compared AI observations to recorded inventory and is
// INFORMATION ONLY. It never modifies inventory. This page never posts anything
// that mutates stock — `/api/reconciliation/run` only writes result rows.

export function ReconciliationPage() {
  const [results, setResults] = useState<ReconciliationResult[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [storeId, setStoreId] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')

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
      const [recRes, prodRes] = await Promise.all([
        reconciliationApi.list(),
        productApi.list(sid ? { store_id: sid } : undefined),
      ])
      setResults(recRes.items)
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

  const runReconciliation = async () => {
    if (!storeId) return
    setRunning(true)
    setError(null)
    try {
      const end = new Date()
      const start = new Date(end.getTime() - 24 * 3600_000)
      await reconciliationApi.run({
        store_id: storeId,
        start: start.toISOString(),
        end: end.toISOString(),
        min_confidence: 0.5,
      })
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setRunning(false)
    }
  }

  const productName = (pid: string) =>
    products.find((p) => p.id === pid)?.name ?? pid.slice(0, 8)

  const tone = (status: string) =>
    status === 'MATCH'
      ? 'green'
      : status === 'POSSIBLE_SHORTAGE'
        ? 'red'
        : status === 'POSSIBLE_SURPLUS'
          ? 'amber'
          : 'purple'

  const visible =
    statusFilter === 'ALL'
      ? results
      : results.filter((r) => r.status === statusFilter)

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <IconScan className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">Reconciliation</h1>
          </div>
          <p className="mt-0.5 text-sm text-gray-500">
            AI observed vs database stock. Informational only — inventory is never
            auto-corrected.
          </p>
        </div>
        <Button onClick={runReconciliation} disabled={running || !storeId}>
          {running ? 'Running…' : 'Run reconciliation'}
        </Button>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading reconciliation…" />
      ) : (
        <Card
          title="Reconciliation Results"
          subtitle="Database vs AI observed quantity for each product"
          action={
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="ALL">All statuses</option>
              <option value="MATCH">MATCH</option>
              <option value="POSSIBLE_SHORTAGE">POSSIBLE_SHORTAGE</option>
              <option value="POSSIBLE_SURPLUS">POSSIBLE_SURPLUS</option>
              <option value="REVIEW_REQUIRED">REVIEW_REQUIRED</option>
            </select>
          }
        >
          {visible.length === 0 ? (
            <EmptyState
              title="No reconciliation results yet"
              hint="Run a reconciliation to compare AI observations against recorded stock. It will not change inventory."
              action={
                storeId ? (
                  <Button onClick={runReconciliation} disabled={running}>
                    {running ? 'Running…' : 'Run reconciliation'}
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table-base w-full min-w-[820px] text-left text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-400">
                    <th className="px-4 py-2.5 font-medium">Product</th>
                    <th className="px-4 py-2.5 font-medium">DB Quantity</th>
                    <th className="px-4 py-2.5 font-medium">AI Observed</th>
                    <th className="px-4 py-2.5 font-medium">Difference</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Confidence</th>
                    <th className="px-4 py-2.5 font-medium">Camera</th>
                    <th className="px-4 py-2.5 font-medium">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {visible.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2.5 font-medium text-gray-800">{productName(r.product_id)}</td>
                      <td className="px-4 py-2.5 text-gray-600">{r.database_quantity}</td>
                      <td className="px-4 py-2.5 text-gray-600">{r.ai_observed_quantity}</td>
                      <td className={`px-4 py-2.5 font-semibold ${r.difference > 0 ? 'text-amber-600' : r.difference < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                        {r.difference > 0 ? `+${r.difference}` : r.difference}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={tone(r.status)}>{r.status}</Badge>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500">
                        {r.confidence != null ? `${Math.round(r.confidence * 100)}%` : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500">
                        {r.camera_id ? r.camera_id.slice(0, 8) + '…' : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-gray-400">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}