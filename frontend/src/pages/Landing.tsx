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
      <header className="sticky top-0 z-40 animate-nav-in border-b border-brand-600/10 bg-white">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex items-center gap-3">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-9 w-auto rounded-lg ring-1 ring-brand-600/20" />
            <span className="text-lg font-semibold tracking-tight text-brand-700">Storeye</span>
          </Link>
          <nav className="ml-auto hidden items-center gap-2 text-sm text-brand-700 md:flex">
            <a
              href="#platform"
              className="rounded-lg border-2 border-brand-600/40 bg-white px-3 py-1.5 font-medium transition-colors duration-200 hover:border-brand-600 hover:bg-brand-600/5"
            >
              Platform
            </a>
            <a
              href="#pipeline"
              className="rounded-lg border-2 border-brand-600/40 bg-white px-3 py-1.5 font-medium transition-colors duration-200 hover:border-brand-600 hover:bg-brand-600/5"
            >
              How it works
            </a>
            <a
              href="#privacy"
              className="rounded-lg border-2 border-brand-600/40 bg-white px-3 py-1.5 font-medium transition-colors duration-200 hover:border-brand-600 hover:bg-brand-600/5"
            >
              Privacy
            </a>
          </nav>
          {isAuthenticated ? (
            <Link to="/app" className="shrink-0 rounded-lg border-2 border-brand-600 bg-white px-4 py-2 text-sm font-medium text-brand-700 transition-colors duration-200 hover:bg-brand-600/5">
              Open dashboard <IconArrowUpRight className="h-4 w-4" />
            </Link>
          ) : (
            <Link to="/login" className="shrink-0 rounded-lg border-2 border-brand-600 bg-white px-4 py-2 text-sm font-medium text-brand-700 transition-colors duration-200 hover:bg-brand-600/5">
              Sign in
            </Link>
          )}
        </div>
      </header>

      {/* First page: full product image with copy just below the navbar */}
      <section className="relative min-h-[calc(100vh-4rem)] w-full overflow-hidden">
        <img
          src="/image1.png"
          alt="Storeye running on a laptop and smartphone"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-x-0 top-0 z-10 mx-auto w-full px-6 pt-12 sm:px-10 lg:px-14">
          <div className="max-w-xl">
            <div className="animate-fade-up">
            <h1 className="group cursor-pointer text-5xl font-bold leading-[1.1] tracking-tight text-brand-700 transition-all duration-500 ease-out hover:scale-[1.04] hover:[filter:drop-shadow(0_10px_28px_rgb(37_99_235_/_0.4))] sm:text-6xl lg:text-7xl">
              Run your store
              <span className="block animate-headline">smarter — even fully offline.</span>
            </h1>
          </div>
            <p
              className="animate-fade-up mt-10 max-w-xl text-lg font-normal leading-relaxed text-brand-600 sm:text-xl"
              style={{ animationDelay: '0.15s' }}
            >
              Storeye turns cameras on your premises into real shelf, queue and revenue
              intelligence. Everything is processed at the edge; your data never leaves
              the building.
            </p>
            <div
              className="animate-fade-up mt-16 flex flex-col items-start gap-3 sm:flex-row"
              style={{ animationDelay: '0.3s' }}
            >
              {isAuthenticated ? (
                <Link to="/app" className="btn-primary px-8 py-4 text-lg">
                  Go to dashboard
                </Link>
              ) : (
                <>
                  <Link to="/login" className="btn-primary px-8 py-4 text-lg">
                    Sign in to Storeye
                  </Link>
                  <Link
                    to="/login"
                    className="inline-flex items-center justify-center gap-2 rounded-lg border-2 border-brand-600/40 bg-white px-8 py-4 text-lg font-medium text-brand-700 transition-colors duration-200 hover:border-brand-600 hover:bg-brand-600/5"
                  >
                    Explore the showcase
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Feature grid */}
      <section id="platform" className="border-t border-brand-600/10 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <p className="text-xs font-bold uppercase tracking-widest text-brand-600">Platform</p>
          <h2 className="mt-2 max-w-2xl text-3xl font-bold tracking-tight text-brand-700 sm:text-4xl">
            One dashboard for everything your store does
          </h2>
          <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-2xl border border-brand-600/10 bg-white p-6 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-600/25 hover:shadow-lift">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600/10 text-brand-600">
                  <f.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold text-brand-700">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-brand-600">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pipeline */}
      <section id="pipeline" className="relative bg-white">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <p className="text-xs font-bold uppercase tracking-widest text-brand-600">How it works</p>
          <h2 className="mt-2 max-w-2xl text-3xl font-bold tracking-tight text-brand-700 sm:text-4xl">
            From camera frames to confident decisions
          </h2>
          <div className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-7">
            {PIPELINE.map((step, i) => (
              <div key={step.label} className="relative flex items-center gap-3 rounded-xl border border-brand-600/10 bg-white p-4">
                <span className="absolute -top-2 left-3 rounded-md bg-brand-600 px-1.5 text-[10px] font-bold text-white">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <step.icon className="h-5 w-5 shrink-0 text-brand-600" />
                <p className="text-sm font-medium leading-tight text-brand-700">{step.label}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 max-w-3xl text-sm text-brand-600">
            The entire loop runs locally. Observation counts feed reconciliation; the
            decision engine surfaces recommendations; staff confirm before anything moves.
          </p>
        </div>
      </section>

      {/* Privacy */}
      <section id="privacy" className="border-t border-brand-600/10 bg-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2 lg:px-8">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-brand-600">Privacy by design</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-brand-700 sm:text-4xl">
              Your store, your data.
              <br />
              No cloud, ever.
            </h2>
            <p className="mt-4 max-w-lg text-base font-normal text-brand-600">
              Storeye was built so EDGE ONLINE + INTERNET OFFLINE is the normal operating
              state. Aggregates never leave the premises, and nothing except the decisions
              you make is ever synced.
            </p>
            <Link to="/login" className="btn-secondary mt-6 inline-flex border-brand-600/30 bg-white px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-600/5 hover:text-brand-700">
              See it for yourself
            </Link>
          </div>
          <ul className="space-y-3">
            {PRIVACY.map((item) => (
              <li key={item} className="flex items-start gap-3 rounded-xl border border-brand-600/10 bg-white p-4">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600/15 text-brand-600">
                  <IconCheck className="h-4 w-4" />
                </span>
                <span className="text-sm text-brand-700">{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* CTA band */}
      <section className="relative bg-white">
        <div className="mx-auto max-w-7xl px-4 pb-20 pt-16 text-center sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl rounded-3xl border border-brand-600/20 bg-brand-600/5 p-8 sm:p-12">
            <h2 className="text-3xl font-bold tracking-tight text-brand-700 sm:text-4xl">
              See your store smarter today
            </h2>
            <p className="mt-3 text-brand-600">
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
      <footer className="border-t border-brand-600/10 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-brand-600 sm:flex-row sm:px-6 lg:px-8">
          <span className="flex items-center gap-2">
            <img src="/storeye-logo.svg" alt="Storeye" className="h-6 w-auto rounded ring-1 ring-brand-600/20" />
            Storeye · Edge AI Retail Intelligence
          </span>
          <span>Offline-first · PostgreSQL on premises · No cloud</span>
        </div>
      </footer>
    </div>
  )
}