// M21: Demo Control Center — switch the deterministic store scenario.
//
// Every scenario is applied by the REAL backend service to the demo store, then
// M20 insights + M16 alerts are re-evaluated. Nothing here is frontend-only:
// reloading the browser keeps the active scenario. Activation never mutates a
// non-demo store (enforced in the backend service layer).

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Modal'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { DEMO_CATEGORY_LABEL, demoApi } from '../lib/api/demo'
import { usePresentationMode } from '../lib/demo/presentation'
import { cleanName } from '../lib/cleanNames'
import type {
  DemoActivationResult,
  DemoScenarioKey,
  DemoScenarioList,
  DemoScenarioStatus,
} from '../lib/api/types'
import { IconArrowUpRight, IconCheck, IconPlay, IconRefresh, IconSparkle } from '../components/ui/icons'

function categoryTone(category: string): 'green' | 'amber' | 'red' | 'blue' | 'purple' | 'gray' {
  if (category === 'healthy') return 'green'
  if (category === 'crisis') return 'red'
  if (category === 'camera') return 'purple'
  if (category === 'customer_flow') return 'blue'
  if (category === 'inventory' || category === 'expiry' || category === 'shelf') return 'amber'
  return 'gray'
}

export function DemoControlCenterPage() {
  const [data, setData] = useState<DemoScenarioList | null>(null)
  const [status, setStatus] = useState<DemoScenarioStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [activating, setActivating] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [presentation, setPresentation] = usePresentationMode()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, st] = await Promise.all([demoApi.listScenarios(), demoApi.status()])
      setData(list)
      setStatus(st)
    } catch (err) {
      setError(err)
      setData(null)
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const describeResult = (res: DemoActivationResult) =>
    `Activated “${res.scenario.name}”. Insights — created ${res.evaluation.created}, ` +
    `refreshed ${res.evaluation.refreshed}, resolved ${res.evaluation.resolved}; ` +
    `alerts — created ${res.evaluation.alerts_created}, updated ${res.evaluation.alerts_updated}.`

  const activate = async (key: DemoScenarioKey) => {
    setActivating(key)
    setError(null)
    setNotice(null)
    try {
      const res = await demoApi.activate(key)
      setNotice(describeResult(res))
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setActivating(null)
    }
  }

  const reset = async () => {
    setActivating('__reset__')
    setError(null)
    setNotice(null)
    try {
      const res = await demoApi.reset()
      setNotice(describeResult(res))
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setActivating(null)
    }
  }

  const activeKey = data?.active_key ?? status?.active_key ?? null
  const activeScenario =
    data?.scenarios.find((s) => s.key === activeKey) ??
    (status?.scenario
      ? { ...status.scenario, expected: [], focus_path: '', active: true }
      : null)

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        eyebrow="Showcase"
        title="Demo Control Center"
        description={
          <>
            Switch the store between deterministic, realistic scenarios. Each switch re-applies the
            REAL backend data and re-evaluates insights &amp; alerts — never a mock or a static image.
          </>
        }
        trailing={
          <>
            <Link
              to="/app/demo/presentation"
              className="inline-flex items-center gap-2 rounded-lg bg-white/[0.04] px-4 py-2 text-sm font-medium text-gray-200 ring-1 ring-inset ring-white/10 transition-colors hover:bg-white/[0.08] hover:text-white"
            >
              Presentation view <IconArrowUpRight className="h-4 w-4" />
            </Link>
            <Button
              kind="secondary"
              onClick={() => setPresentation(!presentation)}
              aria-pressed={presentation}
            >
              {presentation ? 'Exit presentation' : 'Presentation mode'}
            </Button>
            <Button
              kind="secondary"
              onClick={reset}
              disabled={activating !== null || loading}
            >
              {activating === '__reset__' ? 'Resetting…' : 'Reset to Normal'}
            </Button>
          </>
        }
      />

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {notice ? (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200"
        >
          <IconCheck className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{notice}</span>
        </div>
      ) : null}

      {loading ? (
        <Spinner label="Loading scenarios…" />
      ) : !data ? (
        <EmptyState
          title="Demo mode unavailable"
          hint="The backend reports demo mode is disabled, or the demo store is not seeded."
        />
      ) : (
        <>
          {/* Active scenario */}
          <div className="card p-5" data-testid="active-scenario">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Badge tone="blue">
                  <IconSparkle className="h-3.5 w-3.5" /> Active scenario
                </Badge>
                <p className="text-base font-semibold text-gray-100">
                  {activeScenario?.name ?? 'Unknown'}
                </p>
              </div>
              <p className="text-xs text-gray-500">
                {cleanName(data.demo_store)} · {data.scenarios.length} deterministic scenarios
              </p>
            </div>
            {activeScenario ? (
              <>
                <p className="mt-3 text-sm text-gray-400">{activeScenario.description}</p>
                {activeScenario.focus_path ? (
                  <Link
                    to={activeScenario.focus_path}
                    className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-300 hover:underline"
                  >
                    Open the affected view <IconArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                ) : null}
              </>
            ) : null}
            {status?.last_activated_at ? (
              <p className="mt-3 text-xs text-gray-500">
                Last activated {new Date(status.last_activated_at).toLocaleString()}
              </p>
            ) : null}
          </div>

          {/* Scenario grid */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.scenarios.map((scenario) => {
              const isActive = scenario.key === activeKey
              const busy = activating === scenario.key
              return (
                <div
                  key={scenario.key}
                  className={`card flex flex-col p-5 ring-1 ring-inset ${
                    isActive ? 'ring-brand-500/40' : 'ring-white/[0.06]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold tracking-tight text-gray-100">
                      {scenario.name}
                    </h3>
                    <Badge tone={categoryTone(scenario.category)}>
                      {DEMO_CATEGORY_LABEL[scenario.category] ?? scenario.category}
                    </Badge>
                  </div>
                  <p className="mt-2 flex-1 text-sm text-gray-400">{scenario.description}</p>
                  {scenario.expected.length > 0 ? (
                    <ul className="mt-3 space-y-1">
                      {scenario.expected.map((line) => (
                        <li key={line} className="flex gap-2 text-xs text-gray-500">
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-gray-600" aria-hidden="true" />
                          {line}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <div className="mt-4 flex items-center justify-between gap-2">
                    <Button
                      kind={isActive ? 'secondary' : 'primary'}
                      onClick={() => activate(scenario.key)}
                      disabled={busy || isActive || activating !== null}
                      aria-label={`Activate ${scenario.name}`}
                    >
                      {busy ? (
                        'Activating…'
                      ) : isActive ? (
                        <>
                          <IconCheck className="h-4 w-4" /> Active
                        </>
                      ) : (
                        <>
                          <IconPlay className="h-4 w-4" /> Activate
                        </>
                      )}
                    </Button>
                    <Link
                      to={scenario.focus_path}
                      className="inline-flex items-center gap-1 text-xs font-medium text-brand-300 hover:underline"
                    >
                      View <IconArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              )
            })}
          </div>

          <p className="flex items-center gap-2 text-xs text-gray-500">
            <IconRefresh className="h-3.5 w-3.5" />
            Scenarios are stored in the backend database, so a page refresh keeps the current state.
          </p>
        </>
      )}
    </div>
  )
}
