// M30: Periodic Shelf-Occupancy Snapshot API calls.
// Snapshots are OBSERVATIONS — the monitor card reads are pure digests that
// never mutate inventory, batches, bills or sales. Summary/history are served
// from the edge runtime's in-memory mirror when available (Layer-A) and fall
// back to PostgreSQL.

import { api } from './client'
import type { ShelfHistoryResponse, ShelfSnapshotSummary } from './types'

export type ShelfSnapshotParams = {
  store_id: string
  camera_id: string
  shelf_code?: string
  limit?: number
  before?: string
}

export const shelfSnapshotApi = {
  summary: (params: Pick<ShelfSnapshotParams, 'store_id' | 'camera_id'>) =>
    api.get<ShelfSnapshotSummary>('/api/shelf-snapshots/summary', params),
  history: (params: ShelfSnapshotParams) =>
    api.get<ShelfHistoryResponse>('/api/shelf-snapshots/history', params),
  trend: (params: Pick<ShelfSnapshotParams, 'store_id' | 'camera_id'> & { limit?: number }) =>
    api.get<ShelfSnapshotSummary>('/api/shelf-snapshots/trend', params),
}