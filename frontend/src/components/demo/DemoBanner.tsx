// M21: Global presentation-mode banner.
//
// Rendered by the app shell only while presentation mode is ON. It shows the
// deterministic scenario currently active in the backend so a presenter always
// knows the store state, with quick reset / exit controls. Purely a UI aid.

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { demoApi } from '../../lib/api/demo'
import { setPresentationMode, usePresentationMode } from '../../lib/demo/presentation'
import type { DemoScenarioStatus } from '../../lib/api/types'
import { IconClose, IconRefresh, IconSparkle } from '../ui/icons'

export function DemoBanner() {
  const [presentation] = usePresentationMode()
  const [status, setStatus] = useState<DemoScenarioStatus | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setStatus(await demoApi.status())
    } catch {
      setStatus(null) // banner is optional; never block the app
    }
  }, [])

  useEffect(() => {
    if (!presentation) return
    refresh()
  }, [presentation, refresh])

  if (!presentation) return null

  const reset = async () => {
    const ok = window.confirm(
      'Reset the demo store to its baseline? This only affects the deterministic demo data.',
    )
    if (!ok) return
    setBusy(true)
    try {
      await demoApi.reset()
      await refresh()
    } catch {
      // ignore — surfaced on the control center
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sticky top-16 z-20 flex items-center gap-3 border-b border-brand-500/20 bg-brand-500/[0.08] px-4 py-2 text-xs text-brand-100 backdrop-blur">
      <span className="inline-flex items-center gap-1.5 font-semibold">
        <IconSparkle className="h-3.5 w-3.5" /> Presentation mode
      </span>
      <span className="text-brand-200/80">
        Scenario: <span className="font-medium text-brand-100">{status?.scenario?.name ?? '—'}</span>
      </span>
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={reset}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium text-brand-100 hover:bg-white/[0.06] disabled:opacity-50"
        >
          <IconRefresh className="h-3.5 w-3.5" /> {busy ? 'Resetting…' : 'Reset'}
        </button>
        <Link
          to="/app/demo"
          className="rounded-md px-2 py-1 font-medium text-brand-100 hover:bg-white/[0.06]"
        >
          Control center
        </Link>
        <button
          onClick={() => setPresentationMode(false)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium text-brand-100 hover:bg-white/[0.06]"
          aria-label="Exit presentation mode"
        >
          <IconClose className="h-3.5 w-3.5" /> Exit
        </button>
      </div>
    </div>
  )
}
