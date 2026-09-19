import { ApiError, API_BASE, CSRF_HEADER, CSRF_VALUE, NetworkError, request } from './client'
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
    timeoutMs: number = 90_000,
  ): Promise<BatchScanResponse> => {
    const form = new FormData()
    form.append('file', file, file instanceof File ? file.name : 'pack.jpg')
    if (storeId) form.append('store_id', storeId)

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    let res: Response
    try {
      // multipart: let the browser set the Content-Type boundary; never JSON.
      // Always include session cookie and custom CSRF header so authenticated edge node accepts upload.
      res = await fetch(`${API_BASE}/api/batch-intake/scan`, {
        method: 'POST',
        headers: {
          [CSRF_HEADER]: CSRF_VALUE,
        },
        credentials: 'include',
        body: form,
        signal: controller.signal,
      })
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        throw new Error('Package OCR scanning timed out on this device. Please retry or enter details manually.')
      }
      throw new NetworkError(err instanceof Error ? err.message : undefined)
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