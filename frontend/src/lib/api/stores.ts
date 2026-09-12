import { api } from './client'
import type { Store, ApiList } from './types'

export const storeApi = {
  list: () => api.get<ApiList<Store>>('/api/stores'),
  get: (id: string) => api.get<Store>(`/api/stores/${id}`),
  create: (data: { name: string; address?: string | null; city?: string | null; phone?: string | null; timezone?: string }) =>
    api.post<Store>('/api/stores', data),
  update: (id: string, data: Partial<Store>) =>
    api.patch<Store>(`/api/stores/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/stores/${id}`),
}