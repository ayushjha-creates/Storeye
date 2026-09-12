// Authentication foundation for Storeye frontend.
//
// IMPORTANT LIMITATION (documented):
//   The M11 FastAPI backend does NOT yet implement authentication. There is no
//   /api/auth/login endpoint and no user/password verification. This module is a
//   UI-level foundation ONLY:
//     - it gates protected routes and redirects to /login
//     - it persists a session in localStorage so refresh keeps you signed in
//     - it exposes `authenticate()` which WILL call the real backend auth
//       endpoint once it exists (M13+); today it only checks that the local
//       Edge Hub is reachable, then records a local session.
//   Frontend-only auth does NOT provide backend security. Until real auth
//   exists, the API is open at the network layer; nothing here changes that.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { healthApi } from '../lib/api/zone'
import { setAuthToken } from '../lib/api/client'
import { DEMO } from '../config/demo'

export interface AuthSession {
  /** Placeholder identity. Will be replaced by backend-issued values once real auth exists. */
  userName: string
  role: string
  loginAt: string
  /** True when signed in with the public demo account (M18 showcase mode). */
  demo?: boolean
}

const SESSION_KEY = 'storeye.auth.session'
const DEMO_USER = 'Store Manager'

function isDemoCredential(username: string, password: string): boolean {
  return username.trim().toLowerCase() === DEMO.email.toLowerCase() && password === DEMO.password
}

interface AuthContextValue {
  session: AuthSession | null
  isAuthenticated: boolean
  isDemo: boolean
  /** Signs the user in. Returns true on success, throws ApiError/NetworkError on failure. */
  login: (username: string, password: string) => Promise<boolean>
  logout: () => void
  /** Verified only when a real backend JWT is present; a no-op gate today. */
  apiToken: string | null
}

const AuthContext = createContext<AuthContextValue | null>(null)

function loadSession(): AuthSession | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthSession
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => loadSession())
  const [apiToken] = useState<string | null>(
    () => (typeof window !== 'undefined' && window.localStorage.getItem('storeye.auth.token')) || null,
  )

  const login = useCallback(async (username: string, password: string) => {
    // REAL AUTH HOOK POINT (M13+): replace this block with a call to the
    // backend `/api/auth/login` that returns { access_token, user }.
    // For now ensure the local Edge Hub (FastAPI) is reachable, then record a
    // local session. Passing a fake JWT here would be dishonest, so we keep
    // apiToken null until real auth exists.
    await healthApi.health()

    const demo = DEMO.enabled && isDemoCredential(username, password)
    const next: AuthSession = {
      userName: demo ? DEMO.userName : username.trim() || DEMO_USER,
      role: demo ? DEMO.role : 'ASSOCIATE',
      loginAt: new Date().toISOString(),
      demo,
    }
    setSession(next)
    try {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(next))
    } catch {
      // Storage may be unavailable (private mode); session stays in memory.
    }
    return true
  }, [])

  const logout = useCallback(() => {
    setSession(null)
    setAuthToken(null)
    try {
      window.localStorage.removeItem(SESSION_KEY)
    } catch {
      // ignore
    }
  }, [])

  // On first load, sync the stored token into the client so the Authorization
  // header is sent once real auth exists.
  useEffect(() => {
    const stored = window.localStorage.getItem('storeye.auth.token')
    setAuthToken(stored)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: session != null,
      isDemo: session?.demo === true,
      login,
      logout,
      apiToken,
    }),
    [session, login, logout, apiToken],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}