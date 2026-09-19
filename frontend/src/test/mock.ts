// Test helpers: shared fetch mocking for the API client tests.

import { vi } from 'vitest'

export interface MockResponse {
  ok: boolean
  status: number
  json: () => Promise<unknown>
  text: () => Promise<string>
}

export function jsonResponse(body: unknown, status = 200): MockResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

/**
 * Stub the global fetch with a URL-substring route table.
 *
 * value can be either the response body or a `[status, body]` tuple.
 * Route keys are matched by `url.includes(key)`; list more-specific keys first.
 */
export function stubFetchRoutes(routes: Record<string, unknown>): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn() as ReturnType<typeof vi.fn>
  fetchMock.mockImplementation(async (input: string, _init?: RequestInit) => {
    const url = String(input)
    const found = Object.entries(routes).find(([key]) => url.includes(key))
    if (!found) {
      return jsonResponse({ detail: `No mock registered for ${url}` }, 500)
    }
    const value = found[1]
    if (Array.isArray(value) && value.length === 2 && typeof value[0] === 'number') {
      return jsonResponse(value[1], value[0] as number)
    }
    return jsonResponse(value)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function stubFetchReject(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError('Network request failed'))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export const U = (id: string) => id