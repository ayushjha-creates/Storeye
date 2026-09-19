// M16: Storeye Alerts — actionable intelligence API calls.
//
// Alerts are INFORMATIONAL / ACTIONABLE notifications derived from existing
// intelligence. Every call here only reads or updates `alerts` rows: nothing in
// this module (or the backend it talks to) ever mutates inventory, batches,
// bills or sales. Inventory adjustment stays an explicit, human-reviewed step.

import { api } from './client'
import type { Alert, AlertEvaluateResult, AlertType, AlertSeverity, AlertStatus, ApiList } from './types'

export type AlertListParams = {
  store_id?: string | null
  camera_id?: string | null
  product_id?: string | null
  shelf_id?: string | null
  alert_type?: AlertType | null
  severity?: AlertSeverity | null
  status?: AlertStatus | null
  created_from?: string | null
  created_to?: string | null
  limit?: number
  offset?: number
} & Record<string, unknown>

export type AlertCreatePayload = {
  store_id: string
  alert_type: AlertType
  severity: AlertSeverity
  title: string
  message?: string | null
  camera_id?: string | null
  product_id?: string | null
  shelf_id?: string | null
  confidence?: number | null
  source_type?: string | null
  source_id?: string | null
  detected_at?: string | null
  details?: Record<string, unknown> | null
}

export type AlertEvaluatePayload = {
  store_id: string
  camera_id?: string | null
  min_confidence?: number
  alert_confidence_threshold?: number
  hours?: number
  expiry_warning_days?: number | null
  camera_stale_minutes?: number
  reference_date?: string | null
}

export const alertApi = {
  list: (params: AlertListParams) => api.get<ApiList<Alert>>('/api/alerts', params),
  get: (id: string) => api.get<Alert>(`/api/alerts/${id}`),
  create: (body: AlertCreatePayload) => api.post<Alert>('/api/alerts', body),
  evaluate: (body: AlertEvaluatePayload) => api.post<AlertEvaluateResult>('/api/alerts/evaluate', body),
  acknowledge: (id: string) => api.post<Alert>(`/api/alerts/${id}/acknowledge`),
  resolve: (id: string) => api.post<Alert>(`/api/alerts/${id}/resolve`),
  dismiss: (id: string) => api.post<Alert>(`/api/alerts/${id}/dismiss`),
}

export const ALERT_TYPE_LABEL: Record<AlertType, string> = {
  SHORTAGE: 'Shortage',
  SURPLUS: 'Surplus',
  MISPLACEMENT: 'Misplacement',
  EXPIRY: 'Expiry',
  LOW_SHELF_OCCUPANCY: 'Low shelf occupancy',
  SHELF_EMPTY: 'Shelf empty',
  CAMERA_OFFLINE: 'Camera offline',
  REVIEW_REQUIRED: 'Review required',
}

export const ALERT_SEVERITY_ORDER: AlertSeverity[] = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
export const ALERT_STATUS_ORDER: AlertStatus[] = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED']
export const ALERT_TYPE_ORDER: AlertType[] = [
  'SHORTAGE',
  'SURPLUS',
  'MISPLACEMENT',
  'EXPIRY',
  'LOW_SHELF_OCCUPANCY',
  'SHELF_EMPTY',
  'CAMERA_OFFLINE',
  'REVIEW_REQUIRED',
]