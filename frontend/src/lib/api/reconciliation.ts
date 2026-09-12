import { api } from './client'
import type { ReconciliationResult, ApiList } from './types'

export const reconciliationApi = {
  list: (params?: { store_id?: string; product_id?: string; status?: string }) =>
    api.get<ApiList<ReconciliationResult>>('/api/reconciliation', params),
  get: (id: string) => api.get<ReconciliationResult>(`/api/reconciliation/${id}`),
  run: (data: {
    store_id: string
    product_ids?: string[] | null
    camera_id?: string | null
    start: string
    end: string
    min_confidence?: number
  }) => api.post<ApiList<ReconciliationResult>>('/api/reconciliation/run', data),
}