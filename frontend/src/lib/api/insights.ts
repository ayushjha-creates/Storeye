// M20: Storeye Store Intelligence — insight API calls.
//
// Insights are OPERATIONAL observations with evidence + recommended actions.
// They explain "why" (alerts just say "pay attention"). Nothing in this module
// (or the backend it talks to) ever mutates inventory, batches, bills or sales:
// evaluation only reads persisted data and writes/updates `insights` (and, at
// actionable severity, M16 `alerts`).

import { api } from './client'
import type {
  AlertSeverity,
  ApiList,
  Insight,
  InsightCategory,
  InsightEvaluateResult,
  InsightStatus,
  InsightSummary,
  InsightType,
  StoreHealthMetrics,
} from './types'

export type InsightListParams = {
  store_id?: string | null
  category?: InsightCategory | null
  type?: InsightType | null
  severity?: AlertSeverity | null
  status?: InsightStatus | null
  product_id?: string | null
  zone_id?: string | null
  camera_id?: string | null
  limit?: number
  offset?: number
} & Record<string, unknown>

export type InsightEvaluatePayload = {
  store_id: string
  reference_date?: string | null
  now?: string | null
}

export const insightApi = {
  list: (params: InsightListParams) => api.get<ApiList<Insight>>('/api/insights', params),
  get: (id: string) => api.get<Insight>(`/api/insights/${id}`),
  summary: (storeId: string) =>
    api.get<InsightSummary>('/api/insights/summary', { store_id: storeId }),
  storeHealth: (storeId: string) =>
    api.get<StoreHealthMetrics>('/api/insights/store-health', { store_id: storeId }),
  evaluate: (body: InsightEvaluatePayload) => api.post<InsightEvaluateResult>('/api/insights/evaluate', body),
  acknowledge: (id: string) => api.post<Insight>(`/api/insights/${id}/acknowledge`),
  resolve: (id: string) => api.post<Insight>(`/api/insights/${id}/resolve`),
  expire: (id: string) => api.post<Insight>(`/api/insights/${id}/expire`),
}

export const INSIGHT_TYPE_LABEL: Record<string, string> = {
  LOW_STOCK: 'Low stock',
  OUT_OF_STOCK: 'Out of stock',
  LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY: 'Low stock + low shelf',
  HIGH_SELLING_LOW_STOCK: 'High selling, low stock',
  EXPIRY_RISK: 'Expiry risk',
  EXPIRED_BATCH: 'Expired batch',
  STOCK_ROTATION_RECOMMENDATION: 'Stock rotation',
  LOW_SHELF_AVAILABILITY: 'Low shelf availability',
  MISPLACEMENT: 'Misplacement',
  HIGH_TRAFFIC_ZONE: 'High traffic zone',
  HIGH_DWELL_ZONE: 'High dwell zone',
  HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY: 'High traffic, low shelf',
  CAMERA_HEALTH: 'Camera health',
  INVENTORY_RISK: 'Inventory risk',
  STORE_HEALTH: 'Store health',
}

export const INSIGHT_CATEGORY_LABEL: Record<InsightCategory, string> = {
  inventory: 'Inventory',
  shelf: 'Shelf',
  expiry: 'Expiry',
  customer_flow: 'Customer flow',
  camera: 'Camera',
  store_health: 'Store health',
}

export const INSIGHT_SEVERITY_ORDER: AlertSeverity[] = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
export const INSIGHT_STATUS_ORDER: InsightStatus[] = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'EXPIRED']
export const INSIGHT_CATEGORY_ORDER: InsightCategory[] = [
  'inventory',
  'shelf',
  'expiry',
  'customer_flow',
  'camera',
  'store_health',
]
export const INSIGHT_TYPE_ORDER: InsightType[] = [
  'LOW_STOCK',
  'OUT_OF_STOCK',
  'LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY',
  'HIGH_SELLING_LOW_STOCK',
  'EXPIRY_RISK',
  'EXPIRED_BATCH',
  'STOCK_ROTATION_RECOMMENDATION',
  'LOW_SHELF_AVAILABILITY',
  'MISPLACEMENT',
  'HIGH_TRAFFIC_ZONE',
  'HIGH_DWELL_ZONE',
  'HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY',
  'CAMERA_HEALTH',
  'INVENTORY_RISK',
  'STORE_HEALTH',
]