import { api, API_BASE } from './client'
import { DEMO } from '../../config/demo'
import type { MobileIntakeJob } from './types'

const resetKey = DEMO.resetKey || 'storeye-demo-reset'
const guarded = { headers: { 'X-Demo-Reset-Key': resetKey } }

// Fetch the on-disk review photo as an authenticated blob. The photo never
// enters PostgreSQL and is never uploaded to the cloud; fetching it here (with
// the session cookie) avoids relying on cross-origin <img> credentials.
async function intakePhotoBlobUrl(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/mobile-intake/jobs/${jobId}/photo`, {
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Photo unavailable (${res.status})`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export const mobileIntakeApi = {
  status: () => api.get<import('./types').MobileIntakeStatus>('/api/mobile-intake/status'),
  jobs: () => api.get<import('./types').MobileIntakeJobList>('/api/mobile-intake/jobs'),
  job: (jobId: string) => api.get<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}`),
  close: (jobId: string) => api.post<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}/close`),
  rescan: (jobId: string) => api.post<MobileIntakeJob>(`/api/mobile-intake/jobs/${jobId}/rescan`),
  photoBlobUrl: intakePhotoBlobUrl,
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