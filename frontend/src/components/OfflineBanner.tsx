import { useEdge } from '../edge/EdgeContext'

/**
 * Global offline banner. It is split into two concerns so the shopkeeper
 * understands the difference:
 *   - Edge Hub down  -> degraded (most important)
 *   - Internet down  -> NORMAL for Storeye (edge-first), just advisory
 */
export function OfflineBanner() {
  const { status } = useEdge()

  if (status.edgeOnline) {
    if (!status.internetOnline) {
      return (
        <div className="bg-emerald-50 px-4 py-1.5 text-center text-xs font-medium text-emerald-800">
          Internet offline — Storeye is running on the local Edge Node. This is
          normal operation.
        </div>
      )
    }
    return null
  }

  return (
    <div className="bg-red-50 px-4 py-1.5 text-center text-xs font-medium text-red-700">
      Edge node unreachable — the local Storeye backend is offline. Reconnecting…
      Retrying automatically. Any cached data below is read-only.
    </div>
  )
}