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
    <div className="flex min-h-screen bg-[#0a0f1c]">
      {/* Brand panel */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden border-r border-white/[0.06] bg-[#0c1424] p-12 lg:flex">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              'radial-gradient(circle at 18% 8%, rgba(59,130,246,0.22) 0, transparent 42%), radial-gradient(circle at 90% 90%, rgba(139,92,246,0.16) 0, transparent 45%), radial-gradient(rgba(148,163,184,0.05) 1px, transparent 1px)',
            backgroundSize: 'auto, auto, 28px 28px',
          }}
        />
        <div className="relative flex items-center gap-3">
          <Link to="/" className="flex items-center gap-3">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-10 w-auto rounded-lg ring-1 ring-white/10" />
            <div>
              <p className="text-lg font-semibold leading-none text-white">Storeye</p>
              <p className="mt-1 text-xs text-gray-400">AI-powered retail intelligence</p>
            </div>
          </Link>
        </div>

        <div className="relative">
          <h1 className="text-3xl font-bold leading-tight tracking-tight text-white">
            See your store smarter.
            <br />
            Run it better — even fully offline.
          </h1>
          <ul className="mt-8 space-y-4 text-sm text-gray-300">
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.05] ring-1 ring-inset ring-white/10">
                <IconEye className="h-4 w-4 text-brand-300" />
              </span>
              Shelf &amp; product intelligence derived from real Edge AI detections
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.05] ring-1 ring-inset ring-white/10">
                <IconScan className="h-4 w-4 text-brand-300" />
              </span>
              Smart batch receiving from a bar-code camera at the store
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.05] ring-1 ring-inset ring-white/10">
                <IconWifi className="h-4 w-4 text-brand-300" />
              </span>
              Edge-first: everything stays on your premises
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.05] ring-1 ring-inset ring-white/10">
                <IconBox className="h-4 w-4 text-brand-300" />
              </span>
              Inventory, billing and alerts in one dashboard
            </li>
          </ul>
        </div>

        <p className="relative flex items-center gap-2 text-xs text-gray-500">
          <IconActivity className="h-4 w-4" /> Fully offline. Your data never leaves the store.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex w-full flex-col items-center justify-center px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-md">
          <div className="mb-8 flex flex-col items-center lg:hidden">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-12 w-auto" />
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-gray-100">Sign in to Storeye</h1>
          <p className="mt-1 text-sm text-gray-500">
            Access your Storeye Edge Hub — a fully offline retail intelligence dashboard.
          </p>

          <div className="card mt-6 p-6">
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300" htmlFor="username">
                  Name
                </label>
                <input
                  id="username"
                  autoComplete="username"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:border-brand-500/60 focus:bg-white/[0.06] focus:outline-none focus:ring-1 focus:ring-brand-500/30"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Store Manager"
                  required
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300" htmlFor="password">
                  PIN / Password
                </label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:border-brand-500/60 focus:bg-white/[0.06] focus:outline-none focus:ring-1 focus:ring-brand-500/30"
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

            <div className="mt-4 rounded-lg border border-amber-500/25 bg-amber-500/[0.08] px-3 py-2 text-xs text-amber-300">
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