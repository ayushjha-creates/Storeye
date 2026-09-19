// M28: shopkeeper-first AppShell.
//
// The sidebar shows only the eight daily-use destinations (Home, Sales, Stock,
// Receive Stock, Alerts, Reports, Cameras, Settings). Advanced / internal AI
// screens (Product/Shelf Intelligence, AI Observations, Reconciliation,
// Customer Journeys, Insights) are intentionally NOT in the primary nav — they
// stay reachable under Settings → Advanced (and, for the deterministic demo
// store only, a small Demo entry when demo mode is enabled).
//
// Mobile (<lg) uses a fixed bottom bar with the five actions a shopkeeper
// performs most (Home, Sales, Stock, Receive, Alerts) plus More → Settings,
// instead of a long drawer.

import React from 'react'
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { useEdge } from '../../edge/EdgeContext'
import { DemoBanner } from '../demo/DemoBanner'
import { DemoBadge } from '../demo/DemoBadge'
import { ErrorBoundary } from '../ErrorBoundary'
import {
  IconAlert,
  IconBox,
  IconCamera,
  IconChart,
  IconChevronRight,
  IconDashboard,
  IconGear,
  IconLogout,
  IconRupee,
  IconScan,
  IconSparkle,
  IconStore,
} from '../ui/icons'

type NavItemDef = {
  to: string
  label: string
  icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactNode
  end?: boolean
}

const WORKSPACE_NAV: NavItemDef[] = [
  { to: '/app', label: 'Home', icon: IconDashboard, end: true },
  { to: '/app/sales', label: 'Sales', icon: IconRupee, end: true },
  { to: '/app/stock', label: 'Stock', icon: IconBox, end: true },
  { to: '/app/receive', label: 'Receive Stock', icon: IconScan, end: true },
  { to: '/app/alerts', label: 'Alerts', icon: IconAlert },
  { to: '/app/reports', label: 'Reports', icon: IconChart },
]

const OPERATIONS_NAV: NavItemDef[] = [
  { to: '/app/cameras', label: 'Cameras', icon: IconCamera },
  { to: '/app/settings', label: 'Settings', icon: IconGear, end: true },
]

// The five actions that get their own spot on the mobile bottom bar.
const BOTTOM_NAV: (NavItemDef & { to: string })[] = [
  { to: '/app', label: 'Home', icon: IconDashboard, end: true },
  { to: '/app/sales', label: 'Sales', icon: IconRupee, end: true },
  { to: '/app/stock', label: 'Stock', icon: IconBox, end: true },
  { to: '/app/receive', label: 'Receive', icon: IconScan, end: true },
  { to: '/app/alerts', label: 'Alerts', icon: IconAlert },
]

function NavItem({ item, onNavigate }: { item: NavItemDef; onNavigate?: () => void }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
          isActive ? 'bg-brand-50 text-black' : 'text-gray-800 hover:bg-brand-50 hover:text-black'
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

function SidebarContent() {
  const { session, isDemo } = useAuth()
  const { status } = useEdge()
  const storeName = session?.storeName ?? 'Storeye'
  return (
    <>
      <div className="flex items-center gap-3 px-6 py-6">
        <img src="/storeye-logo.svg" alt="Storeye" className="h-9 w-auto rounded-lg ring-1 ring-brand-100" />
        <span className="text-lg font-bold tracking-tight text-black">storeye</span>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <p className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-widest text-gray-500">Workspace</p>
        <nav className="space-y-0.5" aria-label="Main">
          {WORKSPACE_NAV.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </nav>

        <p className="px-3 pb-2 pt-6 text-[10px] font-bold uppercase tracking-widest text-gray-500">Store operations</p>
        <nav className="space-y-0.5" aria-label="Store operations">
          {OPERATIONS_NAV.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
          {isDemo && <NavItem item={{ to: '/app/demo', label: 'Demo', icon: IconSparkle }} />}
        </nav>
      </div>

      <div className="border-t border-gray-200 p-4">
        <div className="mb-3 rounded-lg bg-brand-50 px-3.5 py-2.5 ring-1 ring-inset ring-brand-100">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-900">
            <IconStore className="h-3.5 w-3.5" /> {storeName}
          </p>
          <p className="mt-0.5 text-[10px] text-gray-600">All your data stays on this computer</p>
        </div>
        <div className="flex items-center justify-between text-[10px] text-gray-600">
          <span>{status.edgeOnline ? 'Store running locally' : 'Offline mode'}</span>
          <span className="relative flex h-2 w-2">
            {status.edgeOnline && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            )}
            <span
              className={`relative inline-flex h-2 w-2 rounded-full ${
                status.edgeOnline ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
              aria-hidden="true"
            />
          </span>
        </div>
      </div>
    </>
  )
}

export function AppShell() {
  const { session, logout } = useAuth()
  const { status } = useEdge()

  const storeName = session?.storeName ?? 'Storeye'
  const initials = (session?.userName ?? 'Gu').split(' ').map((s) => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()

  const online = status.edgeOnline
  const statusLabel = online ? 'Store running locally' : 'Offline mode'
  const statusHint = online ? undefined : 'Your store data is still available on this computer.'

  return (
    <div className="relative flex min-h-screen bg-white pb-20 lg:pb-0">
      {/* Desktop sidebar (>=1024px) */}
      <aside className="sticky top-0 z-10 hidden h-screen w-64 shrink-0 flex-col border-r border-gray-200 bg-white shadow-lg lg:flex">
        <SidebarContent />
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-gray-200 bg-white/90 px-3 backdrop-blur-glass sm:px-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <img src="/storeye-logo.svg" alt="" className="h-8 w-auto rounded-lg ring-1 ring-brand-100 lg:hidden" />
            <div className="min-w-0">
              <p className="truncate text-sm font-bold tracking-tight text-gray-900">{storeName}</p>
              <p
                className={`flex items-center gap-1.5 text-[11px] font-medium ${online ? 'text-emerald-700' : 'text-amber-700'}`}
                title={statusHint}
              >
                <span className="relative flex h-2 w-2">
                  {online && (
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  )}
                  <span
                    className={`relative inline-flex h-2 w-2 rounded-full ${
                      online ? 'bg-emerald-500' : 'bg-amber-500'
                    }`}
                    aria-hidden="true"
                  />
                </span>
                {statusLabel}
              </p>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <span className="hidden sm:block">
              <DemoBadge />
            </span>
            <div className="flex items-center gap-2 border-l border-gray-200 pl-3">
              <span
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-bold text-white ring-1 ring-inset ring-brand-200 shadow-sm"
                aria-hidden="true"
              >
                {initials}
              </span>
              <div className="hidden leading-tight md:block">
                <p className="text-sm font-semibold text-gray-900">{session?.userName ?? 'User'}</p>
                <p className="text-xs text-gray-500">{session?.role?.toLowerCase() ?? ''}</p>
              </div>
              <button
                onClick={logout}
                className="flex h-10 w-10 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-brand-50 hover:text-black"
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

        <footer className="hidden items-center justify-between border-t border-gray-200 bg-white px-6 py-3 text-[11px] text-gray-600 lg:flex">
          <span>Storeye · your store's digital assistant</span>
          <Link to="/app/settings" className="text-gray-600 hover:text-black">
            v0.1.0 · offline-first
          </Link>
        </footer>
      </div>

      {/* Mobile bottom bar (<1024px) */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex items-stretch border-t border-gray-200 bg-white shadow-[0_-2px_12px_rgb(0_0_0/0.06)] lg:hidden"
        aria-label="Primary"
      >
        {BOTTOM_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex min-w-0 flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium ${
                isActive ? 'text-brand-700' : 'text-gray-500'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className={`h-5 w-5 ${isActive ? 'text-brand-600' : 'text-gray-500'}`} />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
        <NavLink
          to="/app/settings"
          className={({ isActive }) =>
            `flex min-w-0 flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium ${
              isActive ? 'text-brand-700' : 'text-gray-500'
            }`
          }
        >
          <IconGear className="h-5 w-5" />
          More
        </NavLink>
      </nav>
    </div>
  )
}