// Edge connectivity context.
//
// STOREYE IS EDGE-FIRST. "Internet available" is tracked only as an advisory
// signal: when the browser reports it is offline we surface it, but the app MUST
// remain fully functional. The critical state is "Edge Hub reachable" — i.e.
// whether the LOCAL FastAPI backend (http://localhost:8000) responds.
//
// EDGE ONLINE + INTERNET OFFLINE  = NORMAL OPERATION (storeye keeps working).
// EDGE OFFLINE (backend down)     = degraded: dashboard shows this explicitly,
//                                   and cached/read-only state is used.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { NetworkError } from '../lib/api/client'
import { healthApi } from '../lib/api/zone'

export type EdgeMode = 'online' | 'offline'
export type EngineStatus = 'running' | 'unknown'

export interface EdgeStatus {
  edgeOnline: boolean
  internetOnline: boolean
  engineStatus: EngineStatus
  lastCheckedAt: string | null
  stores: number | null
}

const POLL_INTERVAL_MS = 15_000

const fallback: EdgeStatus = {
  edgeOnline: false,
  internetOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,
  engineStatus: 'unknown',
  lastCheckedAt: null,
  stores: null,
}

interface EdgeContextValue {
  status: EdgeStatus
  refresh: () => Promise<void>
}

const EdgeContext = createContext<EdgeContextValue | null>(null)

export function EdgeProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<EdgeStatus>(fallback)
  const busy = useRef(false)

  const refresh = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    try {
      const internetOnline = typeof navigator !== 'undefined' ? navigator.onLine : true
      let edgeOnline = false
      let engineStatus: EngineStatus = 'unknown'
      let stores: number | null = null
      try {
        await healthApi.health()
        edgeOnline = true
        try {
          const ready = await healthApi.ready()
          stores = ready.stores ?? null
        } catch {
          stores = null
        }
        engineStatus = 'running'
      } catch (err) {
        edgeOnline = false
        engineStatus = 'unknown'
        if (err instanceof NetworkError) {
          // Edge hub unreachable — offline-first mode.
        }
      }
      setStatus({
        edgeOnline,
        internetOnline,
        engineStatus,
        lastCheckedAt: new Date().toISOString(),
        stores,
      })
    } finally {
      busy.current = false
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_INTERVAL_MS)
    const onOnline = () => refresh()
    const onOffline = () =>
      setStatus((s) => ({ ...s, internetOnline: false }))
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') refresh()
    })
    return () => {
      clearInterval(id)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [refresh])

  const value = useMemo<EdgeContextValue>(
    () => ({ status, refresh }),
    [status, refresh],
  )
  return <EdgeContext.Provider value={value}>{children}</EdgeContext.Provider>
}

export function useEdge(): EdgeContextValue {
  const ctx = useContext(EdgeContext)
  if (!ctx) throw new Error('useEdge must be used within <EdgeProvider>')
  return ctx
}