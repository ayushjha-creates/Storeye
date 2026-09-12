import { api } from './client'
import type { Product, ApiList } from './types'

export const productApi = {
  list: (params?: { store_id?: string; category?: string }) =>
    api.get<ApiList<Product>>('/api/products', params),
  get: (id: string) => api.get<Product>(`/api/products/${id}`),
  create: (data: Partial<Product> & { store_id: string; sku: string; name: string }) =>
    api.post<Product>('/api/products', data),
  update: (id: string, data: Partial<Product>) =>
    api.patch<Product>(`/api/products/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/products/${id}`),
}