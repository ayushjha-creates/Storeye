import React, { useState } from 'react'
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { useEdge } from '../../edge/EdgeContext'
import { DemoBanner } from '../demo/DemoBanner'
import { DemoBadge } from '../demo/DemoBadge'
import { ErrorBoundary } from '../ErrorBoundary'
import {
  IconActivity,
  IconAlert,
  IconBell,
  IconBox,
  IconCamera,
  IconChart,
  IconChevronRight,
  IconDashboard,
  IconGear,
  IconLogout,
  IconMenu,
  IconReceipt,
  IconRefresh,
  IconRoute,
  IconScan,
  IconSearch,
  IconShelf,
  IconSparkle,
  IconStore,
  IconTag,
  IconUsers,
  IconWifi,
  IconWifiOff,
  IconClose,
  IconLightbulb,
} from '../ui/icons'

const PRIMARY_NAV: { to: string; label: string; icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactNode; end?: boolean }[] = [
  { to: '/app', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/app/live-store', label: 'Live Store', icon: IconStore },
  { to: '/app/product-intelligence', label: 'Product Intelligence', icon: IconSparkle },
  { to: '/app/shelf-intelligence', label: 'Shelf Intelligence', icon: IconShelf },
  { to: '/app/journeys', label: 'Journeys', icon: IconRoute },
  { to: '/app/insights', label: 'Insights', icon: IconLightbulb },
  { to: '/app/demo', label: 'Demo Control', icon: IconSparkle },
  { to: '/app/alerts', label: 'Alerts', icon: IconAlert },
  { to: '/app/inventory', label: 'Inventory', icon: IconBox, end: true },
  { to: '/app/inventory/receive', label: 'Smart Receiving', icon: IconScan },
  { to: '/app/billing', label: 'Billing', icon: IconReceipt },
  { to: '/app/reports', label: 'Reports & Analytics', icon: IconChart },
  { to: '/app/settings', label: 'Settings', icon: IconGear, end: true },
]

const SECONDARY_NAV: { to: string; label: string; icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactNode }[] = [
  { to: '/app/products', label: 'Products', icon: IconTag },
  { to: '/app/customers', label: 'Customers', icon: IconUsers },
  { to: '/app/cameras', label: 'Cameras', icon: IconCamera },
  { to: '/app/observations', label: 'AI Observations', icon: IconActivity },
  { to: '/app/reconciliation', label: 'Reconciliation', icon: IconRefresh },
]

function NavItem({
  item,
  onNavigate,
}: {
  item: { to: string; label: string; icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactNode; end?: boolean }
  onNavigate?: () => void
}) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
          isActive
            ? 'bg-brand-50 text-black'
            : 'text-gray-800 hover:bg-brand-50 hover:text-black'
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-gradient-to-b from-brand-600 to-cyan-500"
              aria-hidden="true"
            />
          )}
          <span className="ml-1 shrink-0">
            <Icon
              className={`h-[18px] w-[18px] transition-colors ${
                isActive ? 'text-brand-600' : 'text-gray-500 group-hover:text-brand-700'
              }`}
            />
          </span>
          <span className="flex-1">{item.label}</span>
          <IconChevronRight
            className={`h-3.5 w-3.5 transition-opacity ${
              isActive ? 'text-brand-600/80 opacity-100' : 'opacity-0 group-hover:opacity-60'
            }`}
          />
        </>
      )}
    </NavLink>
  )
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { status } = useEdge()
  return (
    <>
      <div className="flex items-center gap-3 px-6 py-6">
        <img src="/storeye-logo.svg" alt="Storeye" className="h-9 w-auto rounded-lg ring-1 ring-brand-100" />
        <span className="text-lg font-bold tracking-tight text-black">storeye</span>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <p className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-widest text-gray-500">
          Workspace
        </p>
        <nav className="space-y-0.5">
          {PRIMARY_NAV.map((item) => (
            <NavItem key={item.to} item={item} onNavigate={onNavigate} />
          ))}
        </nav>

        <p className="px-3 pb-2 pt-6 text-[10px] font-bold uppercase tracking-widest text-gray-500">
          Reference
        </p>
        <nav className="space-y-0.5">
          {SECONDARY_NAV.map((item) => (
            <NavItem key={item.to} item={item} onNavigate={onNavigate} />
          ))}
        </nav>
      </div>

      <div className="border-t border-gray-200 p-4">
        <div className="mb-3 rounded-lg bg-brand-50 px-3.5 py-2.5 ring-1 ring-inset ring-brand-100">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-900">
            <IconStore className="h-3.5 w-3.5" /> Storeye Mart
          </p>
          <p className="mt-0.5 text-[10px] text-gray-600">Offline-first · local PostgreSQL</p>
        </div>
        <div className="flex items-center justify-between text-[10px] text-gray-600">
          <span>Local edge node · PostgreSQL · AI runtime</span>
          <span className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                status.edgeOnline ? 'bg-emerald-500 shadow-[0_0_6px_1px_rgb(16_185_129/0.5)]' : 'bg-amber-500'
              }`}
              aria-hidden="true"
            />
            {status.edgeOnline ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>
    </>
  )
}

export function AppShell() {
  const { session, logout } = useAuth()
  const { status } = useEdge()
  const [mobileOpen, setMobileOpen] = useState(false)

  const initials = (session?.userName ?? 'Gu').split(' ').map((s) => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()

  const topbarBg = 'bg-white/90 backdrop-blur-glass'
  const sidebarBg = 'bg-white text-brand-900'

  const iconBtn =
    'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-brand-50 hover:text-black'

  return (
    <div className="relative flex min-h-screen bg-white">
      {/* Desktop sidebar (>=1024px) */}
      <aside className={`sticky top-0 z-10 hidden h-screen w-64 shrink-0 flex-col border-r border-gray-200 shadow-lg lg:flex ${sidebarBg}`}>
        <SidebarContent />
      </aside>

      {/* Mobile drawer (<1024px) */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className={`absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-gray-200 shadow-xl ${sidebarBg}`}>
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-5 flex h-10 w-10 items-center justify-center rounded-lg text-brand-500 hover:bg-brand-50 hover:text-brand-800"
              aria-label="Close menu"
            >
              <IconClose className="h-5 w-5" />
            </button>
            <div className="pt-14">
              <SidebarContent onNavigate={() => setMobileOpen(false)} />
            </div>
          </aside>
        </div>
      )}

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className={`sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-gray-200 px-3 sm:px-5 ${topbarBg}`}>
          <button
            onClick={() => setMobileOpen(true)}
            className={iconBtn}
            aria-label="Open menu"
          >
            <IconMenu className="h-5 w-5" />
          </button>

          {/* Search: icon-only below 768px, full input above */}
          <div className="relative hidden max-w-md flex-1 md:block">
            <IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand-400" />
            <input
              type="search"
              placeholder="Search products, alerts, bills…"
              aria-label="Search"
              className="h-10 w-full rounded-lg border border-gray-300 bg-white py-2 pl-10 pr-4 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-brand-200"
            />
          </div>
          <button
            className={iconBtn}
            aria-label="Search"
          >
            <IconSearch className="h-5 w-5" />
          </button>

          <div className="flex-1 md:hidden" />

          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <span className="hidden sm:block">
              <DemoBadge />
            </span>
            {/* Edge pill → icon-only below md */}
            <span
              className={`hidden items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium ring-1 ring-inset md:inline-flex ${
                status.edgeOnline
                  ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                  : 'bg-amber-50 text-amber-700 ring-amber-200'
              }`}
            >
              {status.edgeOnline ? <IconWifi className="h-3.5 w-3.5" /> : <IconWifiOff className="h-3.5 w-3.5" />}
              {status.edgeOnline ? 'Edge connected' : 'Edge offline'}
            </span>
            <span
              className={`inline-flex h-10 w-10 items-center justify-center rounded-lg ring-1 ring-inset md:hidden ${
                status.edgeOnline
                  ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                  : 'bg-amber-50 text-amber-700 ring-amber-200'
              }`}
              aria-label={status.edgeOnline ? 'Edge connected' : 'Edge offline'}
            >
              {status.edgeOnline ? <IconWifi className="h-5 w-5" /> : <IconWifiOff className="h-5 w-5" />}
            </span>

            <button
              className={`relative ${iconBtn}`}
              aria-label="Notifications"
            >
              <IconBell className="h-5 w-5" />
              <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-brand-500 ring-2 ring-white" />
            </button>

            <div className="ml-1 flex items-center gap-2.5 border-l border-gray-200 pl-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-bold text-white ring-1 ring-inset ring-brand-200 shadow-sm">
                {initials}
              </span>
              <div className="hidden leading-tight lg:block">
                <p className="text-sm font-semibold text-gray-900">{session?.userName ?? 'Guest'}</p>
                <p className="text-xs text-gray-500">{session?.role}</p>
              </div>
              <button
                onClick={logout}
                className={iconBtn}
                aria-label="Sign out"
                title="Sign out"
              >
                <IconLogout className="h-[18px] w-[18px]" />
              </button>
            </div>
          </div>
        </header>

        <main className="flex-1">
          <DemoBanner />
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>

        <footer className="flex items-center justify-between border-t border-gray-200 bg-white px-6 py-3 text-[11px] text-gray-600">
          <span>Storeye · Edge AI Retail Intelligence</span>
          <Link to="/app/settings" className="text-gray-600 hover:text-black">
            v0.1.0 · offline-first
          </Link>
        </footer>
      </div>
    </div>
  )
}