import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  IconActivity,
  IconArrowUpRight,
  IconBox,
  IconCamera,
  IconCheck,
  IconEye,
  IconReceipt,
  IconScan,
  IconShelf,
  IconStore,
  IconUsers,
  IconWifi,
} from '../components/ui/icons'

const FEATURES = [
  {
    icon: IconShelf,
    title: 'Shelf & product intelligence',
    body: 'YOLO detections mapped to shelves tell you what is low, empty or misplaced — read-only, never auto-adjusts stock.',
  },
  {
    icon: IconScan,
    title: 'Smart batch receiving',
    body: 'Photograph a pack close-up and the local barcode + OCR reads product, batch, MFG, EXP and MRP in seconds.',
  },
  {
    icon: IconUsers,
    title: 'Queue & shopper analytics',
    body: 'Count carts and people at billing to open counters before the rush builds and decide when to move staff.',
  },
  {
    icon: IconReceipt,
    title: 'Billing that understands wait',
    body: 'GST-aware bills, UPI QR and WhatsApp receipts — queued automatically when a threshold is crossed.',
  },
  {
    icon: IconActivity,
    title: 'Reconciliation-first pipeline',
    body: 'Camera observations feed a temporal filter and a decision engine — the system recommends, humans confirm.',
  },
  {
    icon: IconBox,
    title: 'Alerts, tasks and reports',
    body: 'Shortages, expiring batches and misplacements land in one inbox with 30-day revenue and units sold.',
  },
]

const PIPELINE = [
  { label: 'Capture', icon: IconCamera },
  { label: 'Edge inference', icon: IconEye },
  { label: 'Temporal filter', icon: IconActivity },
  { label: 'Reconciliation', icon: IconBox },
  { label: 'Decision engine', icon: IconWifi },
  { label: 'Human confirms', icon: IconCheck },
  { label: 'Staff acts', icon: IconStore },
]

const PRIVACY = [
  'Detection happens on-device; no raw video leaves the store',
  'Anonymous tracker IDs only — no face recognition',
  '30–60 second persistence for person blobs',
  'PostgreSQL on your premises is the source of truth',
  'EDGE ONLINE + INTERNET OFFLINE is the normal state',
]

export function LandingPage() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="min-h-screen overflow-x-hidden text-gray-100">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-surface-100/80 backdrop-blur-glass">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex items-center gap-3">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-9 w-auto rounded-lg ring-1 ring-white/10" />
            <span className="text-lg font-semibold tracking-tight">Storeye</span>
          </Link>
          <nav className="ml-auto hidden items-center gap-6 text-sm text-gray-400 md:flex">
            <a href="#platform" className="hover:text-white">Platform</a>
            <a href="#pipeline" className="hover:text-white">How it works</a>
            <a href="#privacy" className="hover:text-white">Privacy</a>
          </nav>
          {isAuthenticated ? (
            <Link to="/app" className="btn-primary shrink-0">
              Open dashboard <IconArrowUpRight className="h-4 w-4" />
            </Link>
          ) : (
            <Link to="/login" className="btn-primary shrink-0">
              Sign in
            </Link>
          )}
        </div>
      </header>

      {/* Hero */}
      <section className="relative">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              'radial-gradient(1000px 600px at 80% -10%, rgb(59 130 246 / 0.16), transparent 60%), radial-gradient(700px 480px at 8% 30%, rgb(139 92 246 / 0.1), transparent 55%)',
          }}
          aria-hidden="true"
        />
        <div className="relative mx-auto max-w-7xl px-4 pb-20 pt-16 text-center sm:px-6 sm:pt-24 lg:px-8">
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-500/25 bg-brand-500/10 px-3 py-1 text-xs font-medium text-brand-300">
            <IconWifi className="h-3.5 w-3.5" />
            Edge-first · Offline-first · Private by design
          </span>
          <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-bold leading-[1.1] tracking-tight sm:text-6xl">
            Run your store
            <span className="text-accent-gradient block">smarter — even fully offline.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base text-gray-400 sm:text-lg">
            Storeye turns cameras on your premises into real shelf, queue and revenue
            intelligence. Everything is processed at the edge; your data never leaves
            the building.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            {isAuthenticated ? (
              <Link to="/app" className="btn-primary px-6 py-3 text-base">
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link to="/login" className="btn-primary px-6 py-3 text-base">
                  Sign in to Storeye
                </Link>
                <Link to="/login" className="btn-secondary px-6 py-3 text-base">
                  Explore the showcase
                </Link>
              </>
            )}
          </div>

          <div className="mx-auto mt-14 grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { icon: IconWifi, stat: 'EDGE ONLINE', sub: 'internet offline is normal' },
              { icon: IconEye, stat: 'YOLO + ByteTrack', sub: 'people & shelf tracking' },
              { icon: IconReceipt, stat: 'GST + UPI + WhatsApp', sub: 'billing-aware' },
              { icon: IconBox, stat: 'Reconciliation-first', sub: 'humans confirm, never auto-fix' },
            ].map((f) => (
              <div key={f.stat} className="card rounded-xl p-4 text-left">
                <f.icon className="h-5 w-5 text-brand-400" />
                <p className="mt-2 text-sm font-semibold text-gray-800">{f.stat}</p>
                <p className="mt-0.5 text-xs text-gray-500">{f.sub}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Feature grid */}
      <section id="platform" className="border-t border-white/[0.06] bg-surface-200/60">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <p className="text-xs font-bold uppercase tracking-widest text-brand-400">Platform</p>
          <h2 className="mt-2 max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
            One dashboard for everything your store does
          </h2>
          <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="card rounded-2xl p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-white/[0.14] hover:shadow-lift">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500/10 text-brand-400">
                  <f.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold text-gray-800">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-gray-500">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pipeline */}
      <section id="pipeline" className="relative">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <p className="text-xs font-bold uppercase tracking-widest text-brand-400">How it works</p>
          <h2 className="mt-2 max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
            From camera frames to confident decisions
          </h2>
          <div className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-7">
            {PIPELINE.map((step, i) => (
              <div key={step.label} className="relative flex items-center gap-3 rounded-xl border border-white/[0.08] bg-surface-200/70 p-4">
                <span className="absolute -top-2 left-3 rounded-md bg-brand-600 px-1.5 text-[10px] font-bold text-white">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <step.icon className="h-5 w-5 shrink-0 text-brand-400" />
                <p className="text-sm font-medium leading-tight text-gray-300">{step.label}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 max-w-3xl text-sm text-gray-500">
            The entire loop runs locally. Observation counts feed reconciliation; the
            decision engine surfaces recommendations; staff confirm before anything moves.
          </p>
        </div>
      </section>

      {/* Privacy */}
      <section id="privacy" className="border-t border-white/[0.06] bg-surface-200/60">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2 lg:px-8">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-brand-400">Privacy by design</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
              Your store, your data.
              <br />
              No cloud, ever.
            </h2>
            <p className="mt-4 max-w-lg text-gray-400">
              Storeye was built so EDGE ONLINE + INTERNET OFFLINE is the normal operating
              state. Aggregates never leave the premises, and nothing except the decisions
              you make is ever synced.
            </p>
            <Link to="/login" className="btn-secondary mt-6 inline-flex">
              See it for yourself
            </Link>
          </div>
          <ul className="space-y-3">
            {PRIVACY.map((item) => (
              <li key={item} className="flex items-start gap-3 rounded-xl border border-white/[0.07] bg-surface-200/70 p-4">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                  <IconCheck className="h-4 w-4" />
                </span>
                <span className="text-sm text-gray-300">{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* CTA band */}
      <section className="relative">
        <div className="mx-auto max-w-7xl px-4 pb-20 pt-16 text-center sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl rounded-3xl border border-brand-500/20 bg-gradient-to-br from-brand-500/10 to-violet-500/5 p-8 sm:p-12">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">See your store smarter today</h2>
            <p className="mt-3 text-gray-400">
              Sign in and explore the full Storeye hub — live store, reconciliation,
              billing, reports and the Edge AI console.
            </p>
            <Link
              to={isAuthenticated ? '/app' : '/login'}
              className="btn-primary mt-7 px-7 py-3 text-base"
            >
              Start exploring
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-gray-500 sm:flex-row sm:px-6 lg:px-8">
          <span className="flex items-center gap-2">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-6 w-auto rounded ring-1 ring-white/10" />
            Storeye · Edge AI Retail Intelligence
          </span>
          <span>Offline-first · PostgreSQL on premises · No cloud</span>
        </div>
      </footer>
    </div>
  )
}