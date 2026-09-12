import { api } from './client'
import type { HealthStatus, Readiness, Store, ApiList, Zone, Shelf } from './types'
import { storeApi } from './stores'

export const healthApi = {
  health: () => api.get<HealthStatus>('/api/health'),
  ready: () => api.get<Readiness>('/api/ready'),
}

export const edgeApi = {
  health: healthApi.health,
  ready: healthApi.ready,
}

export const zoneApi = {
  list: (params?: { store_id?: string }) => api.get<ApiList<Zone>>('/api/zones', params),
  create: (data: { store_id: string; name: string; description?: string | null }) =>
    api.post<Zone>('/api/zones', data),
}

export const shelfApi = {
  list: (params?: { store_id?: string }) => api.get<ApiList<Shelf>>('/api/shelves', params),
  create: (data: { store_id: string; zone_id: string; code: string; description?: string | null }) =>
    api.post<Shelf>('/api/shelves', data),
}

export { storeApi }
export type { Store }