import { api } from './client'
import type { Sale, ApiList } from './types'

export interface SalePayloadItem {
  product_id: string
  quantity: number
  unit_price: number
  tax: number
  line_total: number
}

export interface SalePayload {
  store_id: string
  subtotal: number
  tax_total: number
  total: number
  payment_method?: string | null
  customer_id?: string | null
  items: SalePayloadItem[]
}

export const saleApi = {
  list: (params?: { store_id?: string }) =>
    api.get<ApiList<Sale>>('/api/sales', params),
  get: (id: string) => api.get<Sale>(`/api/sales/${id}`),
  create: (data: SalePayload) => api.post<Sale>('/api/sales', data),
  remove: (id: string) => api.delete<void>(`/api/sales/${id}`),
}