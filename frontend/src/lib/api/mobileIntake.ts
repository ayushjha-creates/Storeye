import { api } from './client'
import { DEMO } from '../../config/demo'
import type { MobileIntakeJob } from './types'

const resetKey = DEMO.resetKey || 'storeye-demo-reset'
const guarded = { headers: { 'X-Demo-Reset-Key': resetKey } }

export const mobileIntakeApi = {
  status: () => api.get<import('./types').MobileIntakeStatus>('/api/mobile-intake/status'),
  jobs: () => api.get<import('./types').MobileIntakeJobList>('/api/mobile-intake/jobs'),
  job: (jobId: string) => api.get<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}`),
  close: (jobId: string) => api.post<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}/close`),
  rescan: (jobId: string) => api.post<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}/rescan`),
  queueDemoPackage: (product?: string) =>
    api.post<{
      queued: boolean
      filename: string
      size: number
      sha256: string
      demo: boolean
      product?: { slug: string; product_name: string; barcode: string; batch: string }
      note: string
    }>('/api/mobile-intake/demo-queue', product ? { product } : undefined, guarded),
}