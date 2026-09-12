import { api } from './client'
import type { Customer, ApiList } from './types'

export const customerApi = {
  list: (params?: { store_id?: string }) =>
    api.get<ApiList<Customer>>('/api/customers', params),
  get: (id: string) => api.get<Customer>(`/api/customers/${id}`),
  create: (data: { store_id: string; mobile: string; name?: string | null }) =>
    api.post<Customer>('/api/customers', data),
  update: (id: string, data: Partial<Customer>) =>
    api.patch<Customer>(`/api/customers/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/customers/${id}`),
}