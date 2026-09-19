// M15: Storeye Product & Shelf Intelligence API calls.
// All endpoints are PURE READ digests derived from real Edge AI observations.
// None of them can mutate inventory, batches, bills or sales. Labels on the
// UI surface "Visible quantity" / "AI-estimated" semantics from the backend.

import { api } from './client'
import type {
  AISummary,
  ApiList,
  MisplacementRow,
  ProductCandidateRow,
  ProductIntelligenceRow,
  ShelfIntelligenceRow,
} from './types'

export type IntelligenceParams = {
  store_id: string
  camera_id?: string | null
  product_id?: string | null
  class_name?: string | null
  min_confidence?: number
  hours?: number
} & Record<string, unknown>

export const intelligenceApi = {
  products: (params: IntelligenceParams) =>
    api.get<ApiList<ProductIntelligenceRow>>('/api/intelligence/products', params),
  productCandidates: (params: IntelligenceParams) =>
    api.get<ApiList<ProductCandidateRow>>('/api/intelligence/product-candidates', params),
  shelves: (params: IntelligenceParams) =>
    api.get<ApiList<ShelfIntelligenceRow>>('/api/intelligence/shelves', params),
  misplacements: (params: IntelligenceParams) =>
    api.get<ApiList<MisplacementRow>>('/api/intelligence/misplacements', params),
  summary: (params: { store_id: string; hours?: number }) =>
    api.get<AISummary>('/api/intelligence/summary', params),
}

export const COMPARISON_STATUS_LABEL: Record<string, string> = {
  MATCH: 'Visible matches inventory',
  POSSIBLE_SHORTAGE: 'Possible shortage (fewer visible than recorded)',
  POSSIBLE_SURPLUS: 'Possible surplus (more visible than recorded)',
  NO_INVENTORY: 'No inventory record',
  NOT_ASSESSED: 'Unknown product — map to catalog',
}

export const SHELF_STATE_LABEL: Record<string, string> = {
  UNKNOWN: 'Unknown — no AI data',
  EMPTY_VISIBLE: 'Empty (visible)',
  LOW_VISIBLE: 'Low (visible)',
  NORMAL_VISIBLE: 'OK (visible)',
}