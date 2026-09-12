import { api } from './client'
import type { Observation, ApiList, ObservationSummary, ObservationType } from './types'

export interface ObservationPayload {
  observation_type: ObservationType | string
  store_id?: string | null
  camera_id?: string | null
  product_id?: string | null
  batch_id?: string | null
  track_id?: number | null
  frame_number?: number | null
  source?: string | null
  confidence?: number | null
  bbox?: number[] | null
  text?: string | null
  source_observation_id?: string | null
  observed_at?: string | null
}

export interface ObservationListParams {
  store_id?: string
  camera_id?: string
  product_id?: string
  observation_type?: string
  confidence_min?: number
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export interface ObservationSummaryParams {
  store_id?: string
  camera_id?: string
  product_id?: string
  observation_type?: string
  confidence_min?: number
  hours?: number
}

export const observationApi = {
  list: (params?: ObservationListParams) =>
    api.get<ApiList<Observation>>('/api/observations', params as Record<string, unknown>),
  summary: (params?: ObservationSummaryParams) =>
    api.get<ObservationSummary>(
      '/api/observations/summary',
      params as Record<string, unknown>,
    ),
  get: (id: string) => api.get<Observation>(`/api/observations/${id}`),
  create: (data: ObservationPayload) =>
    api.post<Observation>('/api/observations', data),
}