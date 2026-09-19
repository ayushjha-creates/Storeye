import { api } from './client'
import type { ApiList, SmsMessage, SmsStatus, SmsStatusRead } from './types'

export const smsApi = {
  list: (params?: { store_id?: string; bill_id?: string; status?: SmsStatus; limit?: number }) =>
    api.get<ApiList<SmsMessage>>('/api/sms/messages', params),
  status: (params?: { store_id?: string }) => api.get<SmsStatusRead>('/api/sms/status', params),
  resend: (id: string) => api.post<SmsMessage>(`/api/sms/messages/${id}/resend`),
}