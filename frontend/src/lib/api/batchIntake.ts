import { ApiError, API_BASE, NetworkError, REQUEST_TIMEOUT_MS, request } from './client'
import type { BatchConfirmIn, BatchReceipt, BatchScanResponse } from './types'

/**
 * Smart Batch Intake API (M17).
 *
 * `scan` uploads a close-up package photo (multipart). It is READ-ONLY on the
 * backend — nothing is committed. `confirm` commits the human-approved
 * candidate atomically (batch + inventory + movement) through the existing
 * domain services.
 */
export const batchIntakeApi = {
  scan: async (
    file: File | Blob,
    storeId?: string | null,
    timeoutMs: number = REQUEST_TIMEOUT_MS * 4,
  ): Promise<BatchScanResponse> => {
    const form = new FormData()
    form.append('file', file, file instanceof File ? file.name : 'pack.jpg')
    if (storeId) form.append('store_id', storeId)

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    let res: Response
    try {
      // multipart: let the browser set the Content-Type boundary; never JSON.
      res = await fetch(`${API_BASE}/api/batch-intake/scan`, {
        method: 'POST',
        body: form,
        signal: controller.signal,
      })
    } catch {
      throw new NetworkError()
    } finally {
      clearTimeout(timer)
    }
    const text = await res.text()
    let data: unknown = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = text
    }
    if (!res.ok) {
      throw new ApiError(res.status, data)
    }
    return data as BatchScanResponse
  },

  confirm: (payload: BatchConfirmIn) =>
    request<BatchReceipt>('POST', '/api/batch-intake/confirm', payload),
}