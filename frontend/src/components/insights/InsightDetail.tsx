// M20: Insight evidence detail — the "Why?" behind an operational insight.
//
// Renders the persisted evidence blob (rule, human-readable summary, metrics,
// entity context) plus the recommended action and lifecycle. Evidence is
// metadata only — no frames, no identities. This panel never mutates anything.

import { Badge } from '../ui/Badge'
import { Modal } from '../ui/Modal'
import { CertaintyBadge, SeverityBadge, StatusBadge } from './InsightBadges'
import { INSIGHT_CATEGORY_LABEL, INSIGHT_TYPE_LABEL } from '../../lib/api/insights'
import type { Insight } from '../../lib/api/types'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function valueToText(value: unknown): string {
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}

export function InsightDetail({
  insight,
  onClose,
}: {
  insight: Insight
  onClose: () => void
}) {
  const evidence = insight.evidence ?? {}
  const summary: string[] = Array.isArray(evidence.summary)
    ? evidence.summary.filter((s): s is string => typeof s === 'string')
    : []
  const metrics =
    typeof evidence.metrics === 'object' && evidence.metrics !== null
      ? (evidence.metrics as Record<string, unknown>)
      : {}
  const leftover = Object.entries(evidence).filter(
    ([key, value]) =>
      key !== 'rule' && key !== 'summary' && key !== 'metrics' && value !== null && value !== undefined,
  )

  return (
    <Modal
      open
      onClose={onClose}
      title={`${INSIGHT_TYPE_LABEL[insight.insight_type] ?? insight.insight_type} — insight detail`}
      wide
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={insight.severity} />
          <StatusBadge status={insight.status} />
          <CertaintyBadge certainty={insight.certainty} />
          <Badge tone="purple">{INSIGHT_CATEGORY_LABEL[insight.category] ?? insight.category}</Badge>
          <span className="font-mono text-[11px] text-gray-500">{insight.rule_id}</span>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-gray-900">{insight.title}</h3>
          {insight.description ? <p className="mt-1 text-sm text-gray-600">{insight.description}</p> : null}
        </div>

        {summary.length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Evidence summary</p>
            <ul className="space-y-1">
              {summary.map((line, i) => (
                <li key={i} className="flex gap-2 text-sm text-gray-700">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-500" aria-hidden="true" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {Object.keys(metrics).length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Key metrics</p>
            <table className="w-full table-fixed text-left text-xs">
              <tbody className="divide-y divide-gray-100">
                {Object.entries(metrics).map(([key, value]) => (
                  <tr key={key}>
                    <td className="w-2/5 py-1.5 pr-2 font-medium text-gray-500">{key}</td>
                    <td className="break-words py-1.5 font-mono text-gray-800">{valueToText(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {leftover.length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
              Evidence context (metadata only)
            </p>
            <table className="w-full table-fixed text-left text-xs">
              <tbody className="divide-y divide-gray-100">
                {leftover.map(([key, value]) => (
                  <tr key={key}>
                    <td className="w-2/5 py-1.5 pr-2 font-medium text-gray-500">{key}</td>
                    <td className="break-words py-1.5 font-mono text-gray-800">{valueToText(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {insight.recommended_action ? (
          <div className="rounded-lg border border-brand-100 bg-brand-50 px-3 py-2.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Recommended action</p>
            <p className="mt-1 text-sm text-gray-700">{insight.recommended_action}</p>
          </div>
        ) : null}

        <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">First detected</dt>
            <dd className="font-medium text-gray-700">{formatTime(insight.first_detected_at)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Last detected</dt>
            <dd className="font-medium text-gray-700">{formatTime(insight.last_detected_at)}</dd>
          </div>
          {insight.expires_at ? (
            <div className="flex justify-between gap-3">
              <dt className="text-gray-400">Auto-expires</dt>
              <dd className="font-medium text-gray-700">{formatTime(insight.expires_at)}</dd>
            </div>
          ) : null}
          <div className="flex justify-between gap-3">
            <dt className="text-gray-400">Entity</dt>
            <dd className="max-w-[220px] truncate font-mono text-gray-700">
              {insight.entity_type}:{insight.entity_id}
            </dd>
          </div>
        </dl>

        <p className="text-[11px] text-gray-400">
          Insights are operational findings derived from existing data. Storeye never auto-adjusts
          inventory from an insight — restocking and removals remain explicit, human-reviewed steps.
        </p>
      </div>
    </Modal>
  )
}