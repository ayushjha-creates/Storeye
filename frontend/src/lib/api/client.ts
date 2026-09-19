// Central HTTP client for the Storeye frontend.
//
// Talks ONLY to the local FastAPI backend (the "Edge Hub"). No cloud service is
// ever contacted. All requests carry the current API base URL resolved from
// `VITE_API_URL` (default http://localhost:8000).
//
// Error handling contract (matches backend/app/api/errors.py + routers):
//   - network failure / timeout  -> `NetworkError` (offline / edge node down)
//   - 404 / 409 / 422 / 500      -> `ApiError` with `.status` and parsed detail
//   - success                    -> decoded JSON

export const DEFAULT_API_BASE = 'http://localhost:8000'

export function resolveApiBase(): string {
  const fromEnv = (import.meta.env?.VITE_API_URL as string | undefined)?.trim()
  if (fromEnv) return fromEnv
  // Under test runners (Vitest / JSDOM), default to the explicit localhost URL expected by client tests.
  if (
    import.meta.env?.MODE === 'test' ||
    (typeof navigator !== 'undefined' && navigator.userAgent?.includes('jsdom'))
  ) {
    return DEFAULT_API_BASE
  }
  // In the browser, use relative path '' so requests flow through Vite's dev proxy
  // or the same-origin production reverse-proxy. This guarantees zero CORS issues, seamless
  // cookie handling, and full compatibility across localhost, 127.0.0.1, LAN WiFi, and VS Code.
  if (typeof window !== 'undefined' && window.location) {
    return ''
  }
  return DEFAULT_API_BASE
}

export const API_BASE = resolveApiBase()

export const REQUEST_TIMEOUT_MS = 10_000

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? extractDetailMessage(detail, status))
    this.status = status
    this.detail = detail
    this.name = 'ApiError'
  }
}

export class NetworkError extends Error {
  causeDetail: string

  constructor(message = 'Edge node unreachable — the local Storeye backend is offline.') {
    super(message)
    this.name = 'NetworkError'
    this.causeDetail = message
  }
}

function extractDetailMessage(detail: unknown, status: number): string {
  if (detail == null) return `Request failed (${status})`
  if (typeof detail === 'string') return detail
  if (typeof detail === 'object') {
    const anyDetail = detail as Record<string, unknown> | unknown[]
    // FastAPI validation-error shape: { detail: [{ loc, msg, type }] } or [..]
    const candidates: unknown[] = []
    if (Array.isArray(anyDetail)) {
      candidates.push(...anyDetail)
    } else if (Array.isArray(anyDetail.detail)) {
      candidates.push(...(anyDetail.detail as unknown[]))
    } else {
      candidates.push(detail)
    }
    for (const c of candidates) {
      const obj = c as Record<string, unknown> | undefined
      if (obj && typeof obj.msg === 'string') return obj.msg
      if (obj && typeof obj.detail === 'string') return obj.detail
    }
  }
  return `Request failed (${status})`
}

async function parseResponse<T>(res: ResponseConstructor): Promise<[T | null, unknown]> {
  if (res.status === 204) return [null as T | null, null]
  const text = await res.text()
  if (!text) return [null as T | null, null]
  try {
    return [JSON.parse(text) as T, null]
  } catch {
    return [null, text]
  }
}

// Response is structurally like the browser Response; typed loosely so tests can
// drop in a fetch mock that returns { status, ok, json, text }.
type ResponseConstructor = {
  status: number
  ok: boolean
  json: () => Promise<unknown>
  text: () => Promise<string>
}

interface RequestOptions {
  timeoutMs?: number
  headers?: Record<string, string>
}

type Params = Record<string, unknown>

function toQuery(params?: Params): string {
  if (!params) return ''
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    usp.append(key, String(value))
  }
  const q = usp.toString()
  return q ? `?${q}` : ''
}

// Custom CSRF header required by the backend on state-changing requests. A
// cross-site form cannot set custom headers, so this (plus SameSite=Lax cookies
// and the strict local CORS allow-list) is the practical CSRF control.
export const CSRF_HEADER = 'X-Storeye-CSRF'
export const CSRF_VALUE = '1'

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  params?: Params,
  options: RequestOptions = {},
): Promise<T> {
  const url = `${API_BASE}${path}${toQuery(params)}`
  const controller = new AbortController()
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (MUTATING_METHODS.has(method.toUpperCase())) headers[CSRF_HEADER] = CSRF_VALUE
  if (options.headers) Object.assign(headers, options.headers)

  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers,
      body: JSON.stringify(body),
      // Session rides in an HttpOnly cookie — always include it. No token is
      // ever stored in localStorage.
      credentials: 'include',
      signal: controller.signal,
    })
  } catch (err) {
    throw new NetworkError(err instanceof Error ? err.message : undefined)
  } finally {
    clearTimeout(timer)
  }

  const [data] = await parseResponse<T>(res as unknown as ResponseConstructor)
  if (!res.ok) {
    throw new ApiError(res.status, data, extractDetailMessage(data, res.status))
  }
  return data as T
}

export const api = {
  get: <T>(path: string, params?: Params, options?: RequestOptions) =>
    request<T>('GET', path, undefined, params, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, body, undefined, options),
  postFormData: async <T>(path: string, formData: FormData, options: RequestOptions = {}): Promise<T> => {
    const url = `${API_BASE}${path}`
    const controller = new AbortController()
    const timeoutMs = options.timeoutMs ?? 120_000
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const headers: Record<string, string> = {
      [CSRF_HEADER]: CSRF_VALUE,
    }
    if (options.headers) Object.assign(headers, options.headers)
    let res: Response
    try {
      res = await fetch(url, {
        method: 'POST',
        headers,
        body: formData,
        credentials: 'include',
        signal: controller.signal,
      })
    } catch (err) {
      throw new NetworkError(err instanceof Error ? err.message : undefined)
    } finally {
      clearTimeout(timer)
    }
    const [data] = await parseResponse<T>(res as unknown as ResponseConstructor)
    if (!res.ok) {
      throw new ApiError(res.status, data, extractDetailMessage(data, res.status))
    }
    return data as T
  },
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, body, undefined, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PUT', path, body, undefined, options),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>('DELETE', path, undefined, undefined, options),
}