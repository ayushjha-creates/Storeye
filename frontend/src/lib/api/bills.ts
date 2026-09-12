import { api } from './client'
import type { Bill, ApiList } from './types'

export interface BillPayloadItem {
  product_id: string
  quantity: number
  unit_price: number
  tax: number
  line_total: number
}

export interface BillPayload {
  store_id: string
  bill_number: string
  sale_id?: string | null
  customer_id?: string | null
  subtotal: number
  tax_total: number
  total: number
  delivery_status?: string
  items: BillPayloadItem[]
}

export const billApi = {
  list: (params?: { store_id?: string }) =>
    api.get<ApiList<Bill>>('/api/bills', params),
  get: (id: string) => api.get<Bill>(`/api/bills/${id}`),
  create: (data: BillPayload) => api.post<Bill>('/api/bills', data),
  update: (id: string, data: { delivery_status?: string; customer_id?: string | null }) =>
    api.patch<Bill>(`/api/bills/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/bills/${id}`),
}