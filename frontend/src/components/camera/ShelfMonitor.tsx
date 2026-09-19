import { useCallback, useEffect, useState } from 'react'
import { Badge } from '../ui/Badge'
import { ErrorMessage } from '../ui/ErrorState'
import { shelfSnapshotApi } from '../../lib/api/shelfSnapshots'
import type { Camera, ShelfSnapshotRow, ShelfSnapshotSummary } from '../../lib/api/types'

// M30: Periodic Shelf-Occupancy Monitor card.
//
// Reads GET /api/shelf-snapshots/summary (latest snapshot PER configured
// region). Every number is real: fill percents come from product-box/region
// geometry in real camera frames (0 = disabled is displayed honestly). The
// backend serves this from its in-memory mirror when available and falls back
// to PostgreSQL. Snapshots are OUTPUTS — the monitor never edits stock.

const STATUS_TONE: Record<string, 'green' | 'amber' | 'red' | 'gray'> = {
  FULL: 'green',
  MEDIUM: 'green',
  LOW: 'amber',
  EMPTY: 'red',
  OCCLUDED: 'gray',
}

const STATUS_LABEL: Record<string, string> = {
  FULL: 'Full',
  MEDIUM: 'Half or more',
  LOW: 'Half or less',
  EMPTY: 'Empty',
  OCCLUDED: 'Occluded',
}

function FillBar({ row }: { row: ShelfSnapshotRow }) {
  const pct = Math.max(0, Math.min(100, row.fill_percentage))
  const color =
    row.occluded || row.status === 'OCCLUDED'
      ? 'bg-gray-300'
      : pct >= 70
        ? 'bg-emerald-500'
        : pct >= 35
          ? 'bg-amber-400'
          : 'bg-red-500'
  return (
    <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-gray-200">
      <div
        className={`h-full rounded-full ${color}`}
        style={{ width: `${row.occluded ? 100 : pct}%` }}
        data-testid={`fill-bar-${row.shelf_code}`}
      />
    </div>
  )
}

export function ShelfMonitor({
  camera,
  refreshKey,
}: {
  camera: Camera
  refreshKey?: number
}) {
  const [summary, setSummary] = useState<ShelfSnapshotSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    if (!camera.store_id) return
    try {
      const res = await shelfSnapshotApi.summary({
        store_id: camera.store_id,
        camera_id: camera.id,
      })
      setSummary(res)
      setError(null)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [camera.store_id, camera.id])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load, refreshKey])

  const items = summary?.items ?? []
  const status = summary?.status
  const lastScan = summary?.last_scan_at
  const totalRegions = summary?.total_regions ?? 0
  const countsBadge: Array<[string, number]> = status
    ? (
        [
          ['Full', status.FULL],
          ['Half+', status.MEDIUM],
          ['Low', status.LOW],
          ['Empty', status.EMPTY],
          ['Occluded', status.OCCLUDED],
        ] as Array<[string, number]>
      ).filter(([, n]) => n > 0)
    : []

  return (
    <div className="rounded-xl border border-gray-200 bg-surface-200 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            Shelf occupancy monitor (periodic snapshots)
          </p>
          <p className="mt-0.5 text-sm font-semibold text-gray-900">
            {totalRegions} configured region(s)
          </p>
        </div>
        {lastScan ? (
          <p className="text-[11px] text-gray-400" data-testid="last-scan">
            Last scan {new Date(lastScan).toLocaleTimeString()}
          </p>
        ) : null}
      </header>

      {loading ? (
        <p className="px-4 py-4 text-sm text-gray-400">Loading shelf snapshots…</p>
      ) : error && !summary ? (
        <div className="px-4 py-4">
          <ErrorMessage error={error} compact />
        </div>
      ) : items.length === 0 ? (
        <p className="px-4 py-4 text-sm text-gray-500">
          No shelf snapshots yet. Snapshots are written on a fixed wall-clock
          cadence (default every 30 s) when a camera runs with product
          detection + configured shelf regions.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((row) => (
            <li key={row.shelf_code} className="px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-gray-800">
                    {row.shelf_label ?? row.shelf_code}{' '}
                    <span className="text-gray-400">({row.shelf_code})</span>
                  </p>
                  {row.occluded ? (
                    <p className="text-[11px] text-amber-700">
                      {row.occlusion_note ?? 'Person occluding the region — retry next scan.'}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {row.occluded ? (
                    <Badge tone="gray">OCCLUDED</Badge>
                  ) : (
                    <Badge tone={STATUS_TONE[row.status] ?? 'gray'}>
                      {Math.round(row.fill_percentage)}% ·{' '}
                      {STATUS_LABEL[row.status] ?? row.status}
                    </Badge>
                  )}
                </div>
              </div>
              {!row.occluded ? <FillBar row={row} /> : null}
              {row.status === 'EMPTY' && (
                <div className="mt-1.5 flex items-center gap-1.5 rounded-md bg-red-50 px-2 py-1 text-[11px] font-semibold text-red-700">
                  <span>🚨 Urgent restock needed: shelf is empty</span>
                </div>
              )}
              {row.status === 'LOW' && (
                <div className="mt-1.5 flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700">
                  <span>⚠️ Restock alert: shelf is half or less filled</span>
                </div>
              )}
              <div className="mt-1 flex items-center justify-between text-[11px] text-gray-400">
                <span>
                  {row.product_count} product(s)
                  {row.confidence != null ? ` · ${Math.round(row.confidence * 100)}% conf` : ''}
                </span>
                <span>{new Date(row.observed_at).toLocaleTimeString()}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {countsBadge.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
          {countsBadge.map(([label, n]) => (
            <span key={label} className="rounded bg-gray-100 px-2 py-0.5">
              {label}: {n}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}