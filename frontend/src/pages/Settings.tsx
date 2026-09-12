import { Card } from '../components/ui/Card'
import { EdgeNodeStatus } from '../components/EdgeNodeStatus'
import { useEdge } from '../edge/EdgeContext'
import { useAuth } from '../auth/AuthContext'
import { API_BASE } from '../lib/api/client'
import { IconGear } from '../components/ui/icons'

export function SettingsPage() {
  const { session, logout } = useAuth()
  const edge = useEdge()
  const { edgeOnline, engineStatus, internetOnline } = edge.status

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-gray-100 p-1.5">
          <IconGear className="h-4 w-4 text-brand-600" />
        </span>
        <h1 className="font-bold">Settings</h1>
      </div>

      <EdgeNodeStatus compact={false} />

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

        <Card title="Session" subtitle="Local UI authentication">
          <dl className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-4">
              <dt className="text-gray-500">Signed in as</dt>
              <dd className="text-gray-700">{session?.userName ?? '—'}</dd>
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
          <p className="mt-4 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-300">
            M12 auth is a UI-level foundation only. It verifies the Edge Hub is
            reachable and stores a local session — it does not authenticate against
            a backend. Real sign-in arrives with backend auth in a later milestone.
          </p>
          {session && (
            <button
              onClick={() => logout()}
              className="mt-3 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              Sign out
            </button>
          )}
        </Card>
      </div>
    </div>
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