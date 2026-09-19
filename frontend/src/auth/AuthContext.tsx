// Real authentication for the Storeye frontend.
//
// The backend (FastAPI) owns authentication: it issues an HttpOnly session
// cookie on login and validates it on every request. This context is a thin,
// honest wrapper around that API:
//   - on load it calls GET /api/auth/me to restore the session from the cookie
//   - login/logout/change-password/logout-all call the real endpoints
//   - nothing secret is ever written to localStorage
//
// Security lives on the server (sessions, Argon2id, RBAC, store isolation);
// this layer only reflects the authenticated user in the UI.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { authApi, type AuthUser } from '../lib/api/auth'

export interface AuthSession {
  /** Backend user id. */
  userId: string
  email: string | null
  /** Display name shown across the app (AppShell, Settings). */
  userName: string
  role: string
  storeId: string
  storeName: string | null
  loginAt: string
  /** True when the signed-in store is the local showcase store. */
  demo?: boolean
}

function toSession(user: AuthUser): AuthSession {
  return {
    userId: user.id,
    email: user.email,
    userName: user.name,
    role: user.role,
    storeId: user.store_id,
    storeName: user.store_name,
    loginAt: new Date().toISOString(),
    demo: user.demo_store,
  }
}

interface AuthContextValue {
  session: AuthSession | null
  isAuthenticated: boolean
  isDemo: boolean
  /** True while the initial session restore (GET /api/auth/me) is in flight. */
  isLoading: boolean
  /** Role-level helper. OWNER=3, MANAGER=2, STAFF=1. */
  hasRole: (min: 'OWNER' | 'MANAGER' | 'STAFF') => boolean
  /** True when the signed-in user is an OWNER or MANAGER (advanced areas). */
  canManage: boolean
  /** Signs the user in. Throws ApiError/NetworkError on failure. */
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  logoutAll: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string, confirm: string) => Promise<string>
}

const ROLE_LEVEL: Record<string, number> = { OWNER: 3, MANAGER: 2, STAFF: 1 }

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Restore the session from the HttpOnly cookie on first load.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const user = await authApi.me()
        if (!cancelled) setSession(toSession(user))
      } catch {
        // No cookie / expired / backend offline -> stay signed out.
        if (!cancelled) setSession(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const { user } = await authApi.login(email.trim(), password)
    setSession(toSession(user))
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setSession(null)
    }
  }, [])

  const logoutAll = useCallback(async () => {
    try {
      await authApi.logoutAll()
    } finally {
      setSession(null)
    }
  }, [])

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string, confirm: string) => {
      const { message } = await authApi.changePassword(currentPassword, newPassword, confirm)
      return message
    },
    [],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: session != null,
      isDemo: session?.demo === true,
      hasRole: (min) => (session != null ? (ROLE_LEVEL[session.role] ?? 0) >= (ROLE_LEVEL[min] ?? 0) : false),
      canManage: session != null ? (ROLE_LEVEL[session.role] ?? 0) >= ROLE_LEVEL.MANAGER : false,
      isLoading,
      login,
      logout,
      logoutAll,
      changePassword,
    }),
    [session, isLoading, login, logout, logoutAll, changePassword],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
