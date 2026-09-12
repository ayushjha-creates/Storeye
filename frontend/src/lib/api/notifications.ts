import { api } from './client'
import type { Notification, ApiList } from './types'

export const notificationApi = {
  list: (params?: { store_id?: string; is_read?: boolean; limit?: number }) =>
    api.get<ApiList<Notification>>('/api/notifications', params),
  get: (id: string) => api.get<Notification>(`/api/notifications/${id}`),
  create: (data: {
    store_id: string
    notif_type: string
    title: string
    message?: string | null
    severity?: string
    is_read?: boolean
  }) => api.post<Notification>('/api/notifications', data),
  update: (id: string, data: { is_read?: boolean; severity?: string; title?: string; message?: string | null }) =>
    api.patch<Notification>(`/api/notifications/${id}`, data),
  remove: (id: string) => api.delete<void>(`/api/notifications/${id}`),
}