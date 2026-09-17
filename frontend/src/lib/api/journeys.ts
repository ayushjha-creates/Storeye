import { api } from './client'
import type { JourneyList, JourneyDetail, JourneySummary, ZoneAnalytics } from './types'

export interface JourneyListParams {
  store_id: string
  camera_id?: string
  zone_id?: string
  start?: string
  end?: string
  confidence?: string
  limit?: number
  offset?: number
}

export interface JourneyDetailParams {
  store_id: string
}

export interface JourneySummaryParams {
  store_id: string
  start?: string
  end?: string
}

export interface ZoneAnalyticsParams {
  store_id?: string
  start?: string
  end?: string
}

export const journeyApi = {
  list: (params: JourneyListParams) =>
    api.get<JourneyList>('/api/journeys', params as unknown as Record<string, unknown>),
  get: (globalPersonId: string, params: JourneyDetailParams) =>
    api.get<JourneyDetail>(
      `/api/journeys/${encodeURIComponent(globalPersonId)}`,
      params as unknown as Record<string, unknown>,
    ),
  summary: (params: JourneySummaryParams) =>
    api.get<JourneySummary>('/api/journeys/summary', params as unknown as Record<string, unknown>),
  zoneAnalytics: (zoneId: string, params?: ZoneAnalyticsParams) =>
    api.get<ZoneAnalytics>(
      `/api/zones/${encodeURIComponent(zoneId)}/analytics`,
      params as unknown as Record<string, unknown>,
    ),
}
