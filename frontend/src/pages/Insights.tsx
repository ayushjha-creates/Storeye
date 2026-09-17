// M20: Store Intelligence — operational insights with evidence + actions.
//
// Each row explains "why" (evidence) and suggests "what to do" (recommended
// action). "Evaluate now" runs the domain rules over EXISTING persisted data —
// no camera inference, no network, and never mutates inventory/batches/sales.

import { useCallback, useEffect, useState } from 'react'
import { PageHeader, Stat } from '../components/ui/Card'
import { Button } from '../components/ui/Modal'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { CertaintyBadge, SeverityBadge, StatusBadge } from '../components/insights/InsightBadges'
import { InsightDetail } from '../components/insights/InsightDetail'
import {
  INSIGHT_CATEGORY_LABEL,
  INSIGHT_CATEGORY_ORDER,
  INSIGHT_STATUS_ORDER,
  INSIGHT_TYPE_LABEL,
  insightApi,
} from '../lib/api/insights'
import { storeApi } from '../lib/api/zone'
import type {
  Insight,
  InsightCategory,
  InsightStatus,
  InsightSummary,
  StoreHealthMetrics,
} from '../lib/api/types'

function healthTone(state: string): 'green' | 'amber' | 'red' | 'gray' {
  if (state === 'HEALTHY') return 'green'
  if (state === 'ATTENTION') return 'amber'
  if (state === 'CRITICAL') return 'red'
  return 'gray'
}

export function InsightsPage() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [summary, setSummary] = useState<InsightSummary | null>(null)
  const [health, setHealth] = useState<StoreHealthMetrics | null>(null)
  const [category, setCategory] = useState<InsightCategory | ''>('')
  const [status, setStatus] = useState<InsightStatus | ''>('')
  const [selected, setSelected] = useState<Insight | null>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        sid = stores.items[0]?.id ?? null
      } catch (err) {
        setError(err)
      }
      if (!sid) {
        setInsights([])
        setLoading(false)
        return
      }
      const res = await insightApi.list({
        store_id: sid,
        category: category || null,
        status: status || null,
        limit: 100,
      })
      setInsights(res.items)
      try {
        const s = await insightApi.summary(sid)
        setSummary(s)
      } catch {
        setSummary(null) // summary optional on the page
      }
      try {
        const h = await insightApi.storeHealth(sid)
        setHealth(h)
      } catch {
        setHealth(null) // health summary optional on the page
      }
    } catch (err) {
      setError(err)
      setInsights([])
    } finally {
      setLoading(false)
    }
  }, [category, status])

  useEffect(() => {
    load()
  }, [load])

  const runEvaluate = async () => {
    setEvaluating(true)
    setError(null)
    try {
      const stores = await storeApi.list()
      const sid = stores.items[0]?.id
      if (!sid) return
      await insightApi.evaluate({ store_id: sid })
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setEvaluating(false)
    }
  }

  const runAction = async (
    insight: Insight,
    action: 'acknowledge' | 'resolve',
  ) => {
    try {
      const updated =
        action === 'acknowledge'
          ? await insightApi.acknowledge(insight.id)
          : await insightApi.resolve(insight.id)
      setInsights((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
      if (selected?.id === updated.id) setSelected(updated)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        eyebrow="Store intelligence"
        title="Insights"
        description={
          <>
            Operational findings with evidence — <span className="font-medium">why</span> and{' '}
            <span className="font-medium">what to do</span>. Insights never change stock; actions are
            always human-reviewed.
          </>
        }
        trailing={
          <Button kind="secondary" onClick={runEvaluate} disabled={evaluating || loading}>
            {evaluating ? 'Evaluating…' : 'Evaluate now'}
          </Button>
        }
      />

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading insights…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Insights" value={summary?.total ?? insights.length} hint="store-wide" />
            <Stat
              label="Open"
              value={summary?.open ?? 0}
              tone={summary?.open ? 'warning' : 'default'}
              hint="needs attention"
            />
            <Stat
              label="Acknowledged"
              value={summary?.acknowledged ?? 0}
              hint="reviewed, not yet cleared"
            />
            <Stat
              label="High priority"
              value={summary?.high_priority ?? 0}
              tone={summary?.high_priority ? 'danger' : 'default'}
              hint="active HIGH/CRITICAL"
            />
          </div>

          {health ? (
            <div className="card p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Badge tone={healthTone(health.state)}>{health.state}</Badge>
                  <p className="text-sm font-semibold text-gray-100">Store health</p>
                </div>
                <p className="text-xs text-gray-500">
                  Derived from existing data with a documented formula — no opaque score.
                </p>
              </div>
              {health.basis.length > 0 ? (
                <ul className="mt-3 space-y-1">
                  {health.basis.map((line) => (
                    <li key={line} className="flex gap-2 text-sm text-gray-400">
                      <span
                        className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${
                          health.state === 'CRITICAL' ? 'bg-red-400' : 'bg-amber-400'
                        }`}
                        aria-hidden="true"
                      />
                      {line}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-gray-500">No issues found across the store.</p>
              )}
            </div>
          ) : null}

          <div className="card">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-5 py-4">
              <div>
                <h2 className="text-sm font-semibold tracking-tight text-gray-100">Insight list</h2>
                <p className="mt-0.5 text-xs text-gray-500">
                  Evidence-backed findings by category. Click a row for the full "why".
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value as InsightCategory | '')}
                  aria-label="Filter by category"
                  className="h-9 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 focus:border-brand-500/60 focus:outline-none"
                >
                  <option value="">All categories</option>
                  {INSIGHT_CATEGORY_ORDER.map((c) => (
                    <option key={c} value={c}>
                      {INSIGHT_CATEGORY_LABEL[c]}
                    </option>
                  ))}
                </select>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as InsightStatus | '')}
                  aria-label="Filter by status"
                  className="h-9 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 focus:border-brand-500/60 focus:outline-none"
                >
                  <option value="">All statuses</option>
                  {INSIGHT_STATUS_ORDER.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </header>

            <div className="px-5 py-4">
              {insights.length === 0 ? (
                <EmptyState
                  title="No insights yet"
                  hint="Run “Evaluate now” — it reasons over existing inventory, shelf, journey and camera data."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[860px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-xs uppercase tracking-wide text-gray-500">
                        <th className="py-2 pr-3 font-medium">Insight</th>
                        <th className="py-2 pr-3 font-medium">Category</th>
                        <th className="py-2 pr-3 font-medium">Severity</th>
                        <th className="py-2 pr-3 font-medium">Status</th>
                        <th className="py-2 pr-3 font-medium">Certainty</th>
                        <th className="py-2 pr-3 font-medium">First detected</th>
                        <th className="py-2 font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.05]">
                      {insights.map((insight) => (
                        <tr
                          key={insight.id}
                          className="cursor-pointer hover:bg-white/[0.03]"
                          onClick={() => setSelected(insight)}
                        >
                          <td className="py-3 pr-3">
                            <p className="font-medium text-gray-100">{insight.title}</p>
                            <p className="text-xs text-gray-500">
                              {INSIGHT_TYPE_LABEL[insight.insight_type] ?? insight.insight_type} · {insight.rule_id}
                            </p>
                          </td>
                          <td className="py-3 pr-3 text-gray-400">
                            {INSIGHT_CATEGORY_LABEL[insight.category] ?? insight.category}
                          </td>
                          <td className="py-3 pr-3">
                            <SeverityBadge severity={insight.severity} />
                          </td>
                          <td className="py-3 pr-3">
                            <StatusBadge status={insight.status} />
                          </td>
                          <td className="py-3 pr-3">
                            <CertaintyBadge certainty={insight.certainty} />
                          </td>
                          <td className="py-3 pr-3 text-xs text-gray-400">
                            {new Date(insight.first_detected_at).toLocaleString()}
                          </td>
                          <td className="py-3">
                            <div
                              className="flex items-center gap-1.5"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Button
                                kind="ghost"
                                className="px-2 py-1 text-xs"
                                disabled={insight.status !== 'OPEN'}
                                onClick={() => runAction(insight, 'acknowledge')}
                              >
                                Acknowledge
                              </Button>
                              <Button
                                kind="ghost"
                                className="px-2 py-1 text-xs"
                                disabled={
                                  insight.status !== 'OPEN' && insight.status !== 'ACKNOWLEDGED'
                                }
                                onClick={() => runAction(insight, 'resolve')}
                              >
                                Resolve
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {selected ? <InsightDetail insight={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  )
}