// M21/M27: Persistent real-vs-demo marker.
//
// A subtle, always-visible marker so a presenter (or anyone) can never confuse
// the deterministic demo store with production data. It reads the backend demo
// status: demo stores get an amber "Demo store" link, real stores get a neutral
// "Real data" chip. While the status is unknown it renders nothing, so it is
// safe to mount globally.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { demoApi } from '../../lib/api/demo'
import type { DemoScenarioStatus } from '../../lib/api/types'
import { IconSparkle } from '../ui/icons'

export function DemoBadge() {
  const [status, setStatus] = useState<DemoScenarioStatus | null>(null)

  useEffect(() => {
    let alive = true
    demoApi
      .status()
      .then((s) => {
        if (alive) setStatus(s)
      })
      .catch(() => {
        // Demo badge is optional; never surface an error for it.
      })
    return () => {
      alive = false
    }
  }, [])

  if (!status) return null

  if (!status.store_is_demo) {
    return (
      <span
        title="This store shows real observations from your cameras"
        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-300 ring-1 ring-inset ring-emerald-500/25"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
        Real data
      </span>
    )
  }

  return (
    <Link
      to="/app/demo"
      title="This is the deterministic demo store"
      className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-amber-300 ring-1 ring-inset ring-amber-500/25"
    >
      <IconSparkle className="h-3.5 w-3.5" />
      Demo store
    </Link>
  )
}
