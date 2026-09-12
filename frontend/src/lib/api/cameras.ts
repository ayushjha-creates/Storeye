import { api } from './client'
import type { Camera, ApiList } from './types'

export const cameraApi = {
  list: (params?: { store_id?: string }) =>
    api.get<ApiList<Camera>>('/api/cameras', params),
  get: (id: string) => api.get<Camera>(`/api/cameras/${id}`),
  create: (data: Partial<Camera> & { store_id: string; name: string }) =>
    api.post<Camera>('/api/cameras', data),
  update: (id: string, data: Partial<Camera>) =>
    api.patch<Camera>(`/api/cameras/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/cameras/${id}`),
}