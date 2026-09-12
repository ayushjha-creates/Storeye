import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/ui/Card'
import { ObservationTimeline } from '../components/camera/ObservationTimeline'
import { ErrorMessage } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { observationApi } from '../lib/api/observations'
import { cameraApi } from '../lib/api/cameras'
import { OBSERVATION_TYPES } from '../lib/api/types'
import { IconActivity } from '../components/ui/icons'
import type { Camera, Observation, ObservationSummary } from '../lib/api/types'

// AI Observations history.
//
// Filters and pagination run on the BACKEND (GET /api/observations with
// offset/limit + PostgreSQL-side filters). `total` is the true match count so
// paging stays correct. Header cards show real 24h aggregates from
// GET /api/observations/summary. Everything is real data.

const PAGE_SIZE = 50

export function ObservationsPage() {
  const [observations, setObservations] = useState<Observation[]>([])
  const [cameras, setCameras] = useState<Camera[]>([])
  const [summary, setSummary] = useState<ObservationSummary | null>(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)

  const [cameraFilter, setCameraFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [confFilter, setConfFilter] = useState('') // percent string e.g. '70'
  const [fromFilter, setFromFilter] = useState('') // datetime-local
  const [toFilter, setToFilter] = useState('') // datetime-local

  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(
    async (pg: number, keepLoading = true) => {
      if (keepLoading) setLoading(true)
      setError(null)
      try {
        const toUtc = (v: string) => (v ? new Date(v).toISOString() : undefined)
        const query = {
          camera_id: cameraFilter === 'ALL' ? undefined : cameraFilter,
          observation_type: typeFilter === 'ALL' ? undefined : typeFilter,
          confidence_min: confFilter ? Number(confFilter) / 100 : undefined,
          from: toUtc(fromFilter),
          to: toUtc(toFilter),
          limit: PAGE_SIZE,
          offset: pg * PAGE_SIZE,
        }
        const [obsRes, camRes, sumRes] = await Promise.all([
          observationApi.list(query),
          cameraApi.list(),
          observationApi.summary({
            camera_id: cameraFilter === 'ALL' ? undefined : cameraFilter,
            confidence_min: confFilter ? Number(confFilter) / 100 : undefined,
            hours: 24,
          }),
        ])
        setObservations(obsRes.items)
        setTotal(obsRes.total)
        setCameras(camRes.items)
        setSummary(sumRes)
      } catch (err) {
        setError(err)
      } finally {
        if (keepLoading) setLoading(false)
      }
    },
    [cameraFilter, typeFilter, confFilter, fromFilter, toFilter],
  )

  useEffect(() => {
    load(page)
  }, [load, page])

  const resetFilters = useCallback(() => {
    setCameraFilter('ALL')
    setTypeFilter('ALL')
    setConfFilter('')
    setFromFilter('')
    setToFilter('')
    setPage(0)
  }, [])

  const applyFilter = useCallback((fn: () => void) => {
    fn()
    setPage(0)
  }, [])

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const byType = summary?.by_type ?? {}

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <IconActivity className="h-5 w-5 text-brand-600" />
            <h1 className="font-bold">AI Observations</h1>
          </div>
          <p className="mt-0.5 text-sm text-gray-500">
            Detections recorded by the local Edge AI runtime — observations never change
            inventory automatically.
          </p>
        </div>
      </div>

      {error ? <ErrorMessage error={error} onRetry={() => load(page)} /> : null}

      {loading ? (
        <Spinner label="Loading observations…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <div className="card p-4">
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">Total (24h)</p>
              <p className="mt-1 text-2xl font-bold tabular text-gray-900">{summary?.total ?? 0}</p>
            </div>
            {OBSERVATION_TYPES.map((t) => (
              <div key={t} className="card p-4">
                <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">{t}</p>
                <p className="mt-1 text-2xl font-bold tabular text-gray-900">{byType[t] ?? 0}</p>
              </div>
            ))}
          </div>

          <Card
            title="Observation Timeline"
            subtitle={
              cameraFilter === 'ALL' && typeFilter === 'ALL' && !confFilter && !fromFilter && !toFilter
                ? 'All cameras and types'
                : 'Filtered view'
            }
            action={
              <button
                onClick={resetFilters}
                className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
              >
                Reset filters
              </button>
            }
          >
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <label className="flex flex-col gap-1 text-xs text-gray-500">
                Camera
                <select
                  value={cameraFilter}
                  onChange={(e) => applyFilter(() => setCameraFilter(e.target.value))}
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                >
                  <option value="ALL">All cameras</option>
                  {cameras.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-gray-500">
                Type
                <select
                  value={typeFilter}
                  onChange={(e) => applyFilter(() => setTypeFilter(e.target.value))}
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                >
                  <option value="ALL">All types</option>
                  {OBSERVATION_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-gray-500">
                Min confidence
                <select
                  value={confFilter}
                  onChange={(e) => applyFilter(() => setConfFilter(e.target.value))}
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                >
                  <option value="">Any</option>
                  <option value="50">50%</option>
                  <option value="70">70%</option>
                  <option value="90">90%</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-gray-500">
                From
                <input
                  type="datetime-local"
                  value={fromFilter}
                  onChange={(e) => applyFilter(() => setFromFilter(e.target.value))}
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-gray-500">
                To
                <input
                  type="datetime-local"
                  value={toFilter}
                  onChange={(e) => applyFilter(() => setToFilter(e.target.value))}
                  className="rounded-lg border border-gray-300 px-2 py-1 text-xs"
                />
              </label>
            </div>

            <ObservationTimeline observations={observations} onRefresh={() => load(page, false)} />

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-3">
              <p className="text-xs text-gray-500">
                {total} observation(s) · page {page + 1} of {pages}
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page <= 0}
                  className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ← Previous
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                  disabled={page >= pages - 1}
                  className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}