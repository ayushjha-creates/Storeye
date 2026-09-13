import React, { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/ui/Modal'
import { ErrorMessage } from '../components/ui/ErrorState'
import { NetworkError } from '../lib/api/client'
import { IconActivity, IconBox, IconEye, IconScan, IconWifi } from '../components/ui/icons'

/**
 * Login page.
 *
 * AUTH LIMITATION (see AuthContext.tsx): the backend does not yet implement
 * authentication. This page is a UI foundation — it verifies that the local
 * Edge Hub (FastAPI) is reachable, then records a local session. It does NOT
 * verify credentials and does NOT provide backend security.
 */
export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const from = searchParams.get('from')
    ? decodeURIComponent(searchParams.get('from')!)
    : '/app'

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(
        err instanceof NetworkError
          ? 'Cannot reach the local Storeye Edge Hub. Start the backend (FastAPI on localhost:8000) and retry.'
          : err,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Brand panel — white */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-white p-12 lg:flex">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              'radial-gradient(circle at 18% 8%, rgba(59,130,246,0.12) 0, transparent 42%), radial-gradient(circle at 90% 90%, rgba(59,130,246,0.08) 0, transparent 45%), radial-gradient(rgba(59,130,246,0.16) 1px, transparent 1px)',
            backgroundSize: 'auto, auto, 28px 28px',
          }}
        />
        <div className="relative flex items-center gap-3">
          <Link to="/" className="flex items-center gap-3">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-10 w-auto rounded-lg ring-1 ring-brand-100" />
            <div>
              <p className="text-lg font-semibold leading-none text-brand-700">Storeye</p>
              <p className="mt-1 text-xs text-brand-400">AI-powered retail intelligence</p>
            </div>
          </Link>
        </div>

        <div className="relative">
          <h1 className="text-3xl font-bold leading-tight tracking-tight text-brand-800">
            See your store smarter.
            <br />
            Run it better — even fully offline.
          </h1>
          <ul className="mt-8 space-y-4 text-sm text-brand-800">
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 ring-1 ring-inset ring-brand-200">
                <IconEye className="h-4 w-4 text-brand-600" />
              </span>
              Shelf &amp; product intelligence derived from real Edge AI detections
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 ring-1 ring-inset ring-brand-200">
                <IconScan className="h-4 w-4 text-brand-600" />
              </span>
              Smart batch receiving from a bar-code camera at the store
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 ring-1 ring-inset ring-brand-200">
                <IconWifi className="h-4 w-4 text-brand-600" />
              </span>
              Edge-first: everything stays on your premises
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 ring-1 ring-inset ring-brand-200">
                <IconBox className="h-4 w-4 text-brand-600" />
              </span>
              Inventory, billing and alerts in one dashboard
            </li>
          </ul>
        </div>

        <p className="relative flex items-center gap-2 text-xs text-brand-500">
          <IconActivity className="h-4 w-4 text-brand-600" /> Fully offline. Your data never leaves the store.
        </p>
      </div>

      {/* Form panel — light blue */}
      <div className="flex w-full flex-col items-center justify-center bg-gradient-to-br from-brand-300 via-brand-400 to-brand-500 px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-md">
          <div className="mb-8 flex flex-col items-center lg:hidden">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-12 w-auto rounded-xl ring-1 ring-white/40" />
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-brand-900">Sign in to Storeye</h1>
          <p className="mt-1 text-sm text-brand-800">
            Access your Storeye Edge Hub — a fully offline retail intelligence dashboard.
          </p>

          <div className="mt-6 rounded-card border border-brand-100 bg-white p-6 shadow-soft">
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-brand-700" htmlFor="username">
                  Name
                </label>
                <input
                  id="username"
                  autoComplete="username"
                  className="w-full rounded-lg border border-brand-200 bg-white px-3 py-2.5 text-sm text-brand-900 placeholder-brand-300 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-300"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Store Manager"
                  required
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-brand-700" htmlFor="password">
                  PIN / Password
                </label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-brand-200 bg-white px-3 py-2.5 text-sm text-brand-900 placeholder-brand-300 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-300"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••"
                  required
                />
              </div>

              {error ? <ErrorMessage error={error} compact /> : null}

              <Button type="submit" disabled={busy} kind="primary" className="w-full">
                {busy ? 'Connecting to Edge Hub…' : 'Sign in to Storeye'}
              </Button>
            </form>

            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <span className="font-medium">Note:</span> authentication middleware
              is not yet wired into the backend. This sign-in checks that your
              local Edge Hub (FastAPI) is reachable and records a local session.
              It does not provide backend security yet.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}