import { useMemo } from 'react'
import { Card } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { EmptyState } from '../ui/ErrorState'
import { IconShield } from '../ui/icons'
import type { Observation } from '../../lib/api/types'

// M19: anonymous person Re-ID panel for a single camera.
//
// Maps each local (camera-scoped) ByteTrack track_id to its anonymous global
// person id assigned by the edge Re-ID manager. The global id is an opaque
// appearance hash — no faces, crops, embeddings, or biometrics are ever shown,
// and no identity is inferred.

function reidConfidence(obs: Observation): string | null {
  const value = obs.details?.reid_confidence
  return typeof value === 'string' ? value : null
}

function globalPersonId(obs: Observation): string | null {
  const value = obs.details?.global_person_id
  return typeof value === 'string' ? value : null
}

const CONFIDENCE_TONE: Record<string, 'green' | 'blue' | 'amber' | 'gray'> = {
  HIGH: 'green',
  MEDIUM: 'blue',
  LOW: 'amber',
  UNKNOWN: 'gray',
}

function shortId(id: string | null): string {
  if (!id) return '—'
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-6)}` : id
}

export function ReIdPanel({ observations }: { observations: Observation[] }) {
  const rows = useMemo(() => {
    const persons = observations.filter((o) => o.observation_type === 'PERSON')
    const latest = new Map<number, Observation>()
    for (const o of persons) {
      if (o.track_id == null) continue
      const existing = latest.get(o.track_id)
      if (!existing || new Date(o.observed_at) > new Date(existing.observed_at)) {
        latest.set(o.track_id, o)
      }
    }
    return [...latest.values()]
      .filter((o) => globalPersonId(o) != null)
      .sort((a, b) => new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime())
      .slice(0, 20)
  }, [observations])

  return (
    <Card
      title="Person Re-ID (this camera)"
      subtitle="Local track → anonymous global person id — appearance-only, no identity"
    >
      <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-brand-500/20 bg-brand-500/[0.06] px-3.5 py-2.5">
        <IconShield className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />
        <p className="text-xs text-gray-400">
          Every id is an anonymous cross-camera continuity key. No face, crop,
          embedding, or biometric is stored or returned.
        </p>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No anonymous person associations yet"
          hint="With Re-ID enabled, the edge runtime assigns a global person id to each local track when a shopper is seen across cameras."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-xs uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2 font-medium">Local track</th>
                <th className="px-3 py-2 font-medium">Global person</th>
                <th className="px-3 py-2 font-medium">Confidence</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {rows.map((o) => {
                const gid = globalPersonId(o)
                const conf = reidConfidence(o)
                return (
                  <tr key={`${o.track_id}-${gid}`} className="hover:bg-white/[0.03]">
                    <td className="px-3 py-2.5 font-mono text-[13px] text-gray-300">
                      #{o.track_id}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="font-mono text-[13px] font-medium text-cyan-300">
                        {shortId(gid)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={CONFIDENCE_TONE[conf ?? ''] ?? 'gray'}>
                        {conf ?? 'UNKNOWN'}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-400">
                      {new Date(o.observed_at).toLocaleString()}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}