import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

/**
 * Guards protected routes. Unauthenticated users are redirected to /login with
 * a `from` param so they can be returned after a successful sign-in.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  // Wait for the cookie-based session restore before deciding.
  if (isLoading) return null
  if (!isAuthenticated) {
    const target = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?from=${target}`} replace />
  }
  return <>{children}</>
}

/** Leads already-authenticated users away from /login back to the dashboard. */
export function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  if (isLoading) return null
  if (isAuthenticated) return <Navigate to="/" replace />
  return <>{children}</>
}