// M21: Presentation hub.
//
// A single screen a presenter can keep open: it shows the scenario currently
// active in the backend and deep-links straight to the REAL application pages
// that demonstrate it. No animation, no mock data — every link navigates to the
// actual Storeye UI backed by the scenario state in PostgreSQL.

import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Modal'
import { Badge } from '../components/ui/Badge'
import { ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { DEMO_CATEGORY_LABEL, demoApi } from '../lib/api/demo'
import { usePresentationMode } from '../lib/demo/presentation'
import { cleanName } from '../lib/cleanNames'
import type { DemoScenarioList, DemoScenarioStatus } from '../lib/api/types'
import {
  IconAlert,
  IconArrowUpRight,
  IconBox,
  IconDashboard,
  IconLightbulb,
  IconRoute,
  IconScan,
  IconSparkle,
  IconStore,
} from '../components/ui/icons'

const LINKS: { label: string; to: string; icon: (p: { className?: string }) => ReactNode }[] = [
  { label: 'Open Dashboard', to: '/app', icon: IconDashboard },
  { label: 'Open Live Store', to: '/app/live-store', icon: IconStore },
  { label: 'Open Inventory', to: '/app/inventory', icon: IconBox },
  { label: 'Open Alerts', to: '/app/alerts', icon: IconAlert },
  { label: 'Open Journeys', to: '/app/journeys', icon: IconRoute },
  { label: 'Open Smart Receiving', to: '/app/inventory/receive', icon: IconScan },
  { label: 'Open Insights', to: '/app/insights', icon: IconLightbulb },
]

export function DemoPresentationPage() {
  const [status, setStatus] = useState<DemoScenarioStatus | null>(null)
  const [list, setList] = useState<DemoScenarioList | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [presentation, setPresentation] = usePresentationMode()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [st, catalog] = await Promise.all([demoApi.status(), demoApi.listScenarios()])
      setStatus(st)
      setList(catalog)
    } catch (err) {
      setError(err)
      setStatus(null)
      setList(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const activeKey = list?.active_key ?? status?.active_key ?? null
  const active =
    list?.scenarios.find((s) => s.key === activeKey) ??
    (status?.scenario ? { ...status.scenario, expected: [], focus_path: '' } : null)

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        eyebrow="Storeye Demo Environment"
        title="Presentation"
        description="The scenario active in the backend database, with direct links into the real application pages."
        trailing={
          <>
            <Button
              kind="secondary"
              onClick={() => setPresentation(!presentation)}
              aria-pressed={presentation}
            >
              {presentation ? 'Exit banner' : 'Show banner'}
            </Button>
            <Link
              to="/app/demo"
              className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
            >
              Control center <IconArrowUpRight className="h-4 w-4" />
            </Link>
          </>
        }
      />

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading scenario…" />
      ) : !status ? null : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="card p-5 lg:col-span-2">
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="blue">
                <IconSparkle className="h-3.5 w-3.5" /> Current scenario
              </Badge>
              {active ? (
                <Badge tone="gray">{DEMO_CATEGORY_LABEL[active.category] ?? active.category}</Badge>
              ) : null}
            </div>
            <h2 className="mt-3 text-xl font-semibold tracking-tight text-gray-100">
              {active?.name ?? 'Unknown'}
            </h2>
            <p className="mt-1 text-sm text-gray-400">{active?.description}</p>
            {active && active.expected.length > 0 ? (
              <>
                <p className="mt-5 text-[11px] font-bold uppercase tracking-widest text-gray-500">
                  What is happening
                </p>
                <ul className="mt-2 space-y-1.5">
                  {active.expected.map((line) => (
                    <li key={line} className="flex gap-2 text-sm text-gray-300">
                      <span
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400"
                        aria-hidden="true"
                      />
                      {line}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            <p className="mt-5 text-xs text-gray-500">
              {cleanName(status.demo_store)} · state lives in PostgreSQL, so refreshing the browser
              keeps this scenario active.
            </p>
          </div>

          <div className="card p-5">
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">Go to</p>
            <div className="mt-3 space-y-2">
              {LINKS.map(({ label, to, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-gray-200 transition-colors hover:bg-white/[0.07] hover:text-white"
                >
                  <Icon className="h-4 w-4 text-brand-300" />
                  {label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
