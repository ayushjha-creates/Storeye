import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { EdgeNodeStatus } from '../components/EdgeNodeStatus'
import { useEdge } from '../edge/EdgeContext'
import { useAuth } from '../auth/AuthContext'
import { API_BASE } from '../lib/api/client'
import { ApiError } from '../lib/api/client'
import { IconBox, IconCamera, IconGear, IconSparkle, IconStore, IconTag, IconUsers } from '../components/ui/icons'

export function SettingsPage() {
  const { session, logout, logoutAll, canManage, isDemo } = useAuth()
  const edge = useEdge()
  const { edgeOnline, engineStatus, internetOnline } = edge.status

  const onLogoutAll = async () => {
    try {
      await logoutAll()
    } catch {
      // Even if the request fails, the local session is cleared.
    }
  }

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-gray-100 p-1.5">
          <IconGear className="h-4 w-4 text-brand-600" />
        </span>
        <h1 className="font-bold">Settings</h1>
      </div>

      <EdgeNodeStatus compact={false} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SettingsLink to="/app/products" icon={<IconTag />} title="Products" note="Your product catalog" />
        <SettingsLink to="/app/customers" icon={<IconUsers />} title="Customers" note="Customer records" />
        <SettingsLink to="/app/cameras" icon={<IconCamera />} title="Cameras" note="Camera setup and shelf areas" />
        <SettingsLink to="/app/live-store" icon={<IconStore />} title="Live store" note="Real-time camera activity" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Connection" subtitle="Frontend → Edge Hub (FastAPI)">
          <dl className="space-y-2 text-sm">
            <div className="flex items-start justify-between gap-4">
              <dt className="text-gray-500">API base URL</dt>
              <dd className="font-mono text-gray-700">{API_BASE}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Edge Hub reachable</dt>
              <dd>
                <EdgeHubStatus ok={edgeOnline} />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Engine status</dt>
              <dd className="text-gray-700">{engineStatus ?? 'unknown'}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Internet reachable</dt>
              <dd>{internetOnline ? 'Yes — optional for Storeye to work' : 'No — offline is normal'}</dd>
            </div>
          </dl>
        </Card>

        <Card title="Account" subtitle="Signed in via the local Edge Hub">
          <dl className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Signed in as</dt>
              <dd className="text-gray-700">{session?.userName ?? '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Email</dt>
              <dd className="text-gray-700">{session?.email ?? '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Store</dt>
              <dd className="text-gray-700">{session?.storeName ?? '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Role</dt>
              <dd className="text-gray-700">{session?.role ?? '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Logged in at</dt>
              <dd className="text-gray-700">{session?.loginAt ? new Date(session.loginAt).toLocaleString() : '—'}</dd>
            </div>
          </dl>
          <p className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
            Authentication is enforced by the local Edge Hub (Argon2id passwords +
            HttpOnly session cookie). Your data never leaves the store.
          </p>
          {session && (
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => logout()}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
              >
                Sign out
              </button>
              <button
                onClick={onLogoutAll}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
              >
                Sign out everywhere
              </button>
            </div>
          )}
        </Card>
      </div>

      {session && <ChangePasswordCard />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {canManage && <SettingsLink to="/app/settings/advanced" icon={<IconBox />} title="Advanced" note="Stock activity, AI diagnostics, customer activity, reconciliation" />}
        {isDemo && <SettingsLink to="/app/demo" icon={<IconSparkle />} title="Demo" note="Deterministic demo scenarios and reset" />}
      </div>
    </div>
  )
}

function SettingsLink({ to, icon, title, note }: { to: string; icon: React.ReactNode; title: string; note: string }) {
  return (
    <Link to={to} className="card card-hover p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 ring-1 ring-inset ring-brand-100">
          {icon}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <p className="mt-0.5 text-xs text-gray-500">{note}</p>
        </div>
      </div>
    </Link>
  )
}

function ChangePasswordCard() {
  const { changePassword } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setMessage(null)
    setBusy(true)
    try {
      const msg = await changePassword(current, next, confirm)
      setMessage(msg)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Change password" subtitle="Other sessions will be signed out">
      <form onSubmit={onSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-gray-500">Current password</span>
          <input
            type="password"
            aria-label="Current password"
            autoComplete="current-password"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-gray-500">New password</span>
          <input
            type="password"
            aria-label="New password"
            autoComplete="new-password"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-gray-500">Confirm new password</span>
          <input
            type="password"
            aria-label="Confirm new password"
            autoComplete="new-password"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </label>
        <div className="sm:col-span-3">
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {busy ? 'Updating…' : 'Update password'}
          </button>
          {message && <span className="ml-3 text-xs text-emerald-600">{message}</span>}
          {error && <span className="ml-3 text-xs text-red-600">{error}</span>}
        </div>
      </form>
    </Card>
  )
}

function EdgeHubStatus({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        ok
          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
          : 'border-red-500/25 bg-red-500/10 text-red-300'
      }`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`}
        aria-hidden="true"
      />
      {ok ? 'Yes' : 'No'}
    </span>
  )
}
