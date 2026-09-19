import { describe, it, expect, vi } from 'vitest'
import { api, ApiError, NetworkError } from './client'
import { stubFetchRoutes } from '../../test/mock'

describe('api client', () => {
  it('GET parses a successful JSON payload against the API base', async () => {
    const fetchMock = stubFetchRoutes({
      '/api/stores': { items: [{ id: 's1', name: 'My Store' }], total: 1 },
    })
    const data = await api.get<{ items: { name: string }[] }>('/api/stores')
    expect(data.items[0].name).toBe('My Store')
    expect(fetchMock).toHaveBeenCalled()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/^http:\/\/localhost:8000\/api\/stores/)
    expect(init.method).toBe('GET')
  })

  it('throws ApiError(404) with parsed detail', async () => {
    stubFetchRoutes({ '/api/cameras/': [404, { detail: 'Camera not found' }] })
    const err = await api.get('/api/cameras/nope').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(404)
    expect((err as ApiError).detail).toEqual({ detail: 'Camera not found' })
  })

  it('throws ApiError(409) for a conflict', async () => {
    stubFetchRoutes({ '/api/products': [409, { detail: 'SKU already exists' }] })
    const err = await api.get('/api/products').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).message).toBe('SKU already exists')
  })

  it('maps a 422 validation-error detail array to a readable message', async () => {
    stubFetchRoutes({
      '/api/inventory/receive': [
        422,
        {
          detail: [
            { loc: ['body', 'quantity_change'], msg: 'Input should be greater than 0', type: 'greater_than' },
          ],
        },
      ],
    })
    const err = await api
      .post('/api/inventory/receive', { quantity_change: -1 })
      .catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).message).toContain('greater than 0')
  })

  it('throws ApiError(500) for a server error', async () => {
    stubFetchRoutes({ '/api/health': [500, { detail: 'Internal Server Error' }] })
    const err = await api.get('/api/health').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(500)
  })

  it('throws NetworkError when the edge node is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.get('/api/health')).rejects.toBeInstanceOf(NetworkError)
  })

  it('sends cookies with credentials: include (session auth, no token)', async () => {
    const fetchMock = stubFetchRoutes({ '/api/health': { status: 'ok' } })
    await api.get('/api/health')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.credentials).toBe('include')
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('adds the CSRF header on mutating requests only', async () => {
    const fetchMock = stubFetchRoutes({ '/api/auth/login': { user: {}, expires_in_seconds: 1 } })
    await api.post('/api/auth/login', { email: 'a@b.c', password: 'x' })
    const [, postInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((postInit.headers as Record<string, string>)['X-Storeye-CSRF']).toBe('1')

    const getMock = stubFetchRoutes({ '/api/health': { status: 'ok' } })
    await api.get('/api/health')
    const [, getInit] = getMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((getInit.headers as Record<string, string>)['X-Storeye-CSRF']).toBeUndefined()
  })

  it('adds query params correctly and skips empty values', async () => {
    const fetchMock = stubFetchRoutes({ '/api/observations': { items: [], total: 0 } })
    await api.get('/api/observations', { store_id: undefined, limit: 5, camera_id: '' })
    const [url] = fetchMock.mock.calls[0] as unknown as [string]
    expect(url).toContain('?limit=5')
    expect(url).not.toContain('store_id')
  })

  it('submits a JSON body on POST', async () => {
    const fetchMock = stubFetchRoutes({ '/api/bills': { items: [], total: 0 } })
    await api.post('/api/bills', { total: 99 })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/bills')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(init.body).toContain('"total":99')
  })
})