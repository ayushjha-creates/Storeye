import React, { useState } from 'react'
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { useEdge } from '../../edge/EdgeContext'
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
} from '../ui/icons'

const PRIMARY_NAV: { to: string; label: string; icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactNode; end?: boolean }[] = [
  { to: '/app', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/app/live-store', label: 'Live Store', icon: IconStore },
  { to: '/app/product-intelligence', label: 'Product Intelligence', icon: IconSparkle },
  { to: '/app/shelf-intelligence', label: 'Shelf Intelligence', icon: IconShelf },
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
            ? 'bg-white/[0.06] text-white'
            : 'text-gray-400 hover:bg-white/[0.04] hover:text-gray-100'
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-gradient-to-b from-brand-400 to-cyan-400"
              aria-hidden="true"
            />
          )}
          <span className="ml-1 shrink-0">
            <Icon
              className={`h-[18px] w-[18px] transition-colors ${
                isActive ? 'text-brand-300' : 'text-gray-500 group-hover:text-gray-200'
              }`}
            />
          </span>
          <span className="flex-1">{item.label}</span>
          <IconChevronRight
            className={`h-3.5 w-3.5 transition-opacity ${
              isActive ? 'text-brand-400/80 opacity-100' : 'opacity-0 group-hover:opacity-60'
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
        <img src="/storeye-logo.svg" alt="Storeye" className="h-9 w-auto rounded-lg ring-1 ring-white/10" />
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

      <div className="border-t border-white/[0.06] p-4">
        <div className="mb-3 rounded-lg bg-white/[0.04] px-3.5 py-2.5 ring-1 ring-inset ring-white/[0.07]">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-brand-300">
            <IconStore className="h-3.5 w-3.5" /> Storeye Mart
          </p>
          <p className="mt-0.5 text-[10px] text-gray-500">Offline-first · local PostgreSQL</p>
        </div>
        <div className="flex items-center justify-between text-[10px] text-gray-500">
          <span>Local edge node · PostgreSQL · AI runtime</span>
          <span className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                status.edgeOnline ? 'bg-emerald-400 shadow-[0_0_6px_1px_rgb(52_211_153/0.5)]' : 'bg-amber-400'
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

  const topbarBg = 'bg-[#0a0f1c]/85 backdrop-blur-glass'
  const sidebarBg = 'bg-[#0c1424] text-white'

  const iconBtn =
    'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-white/[0.05] hover:text-gray-100'

  return (
    <div className="flex min-h-screen bg-surface-100">
      {/* Desktop sidebar (>=1024px) */}
      <aside className={`sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-white/[0.06] shadow-2xl lg:flex ${sidebarBg}`}>
        <SidebarContent />
      </aside>

      {/* Mobile drawer (<1024px) */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className={`absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-white/[0.08] shadow-2xl ${sidebarBg}`}>
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-5 flex h-10 w-10 items-center justify-center rounded-lg text-gray-400 hover:bg-white/[0.06] hover:text-gray-100"
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

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className={`sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-white/[0.06] px-3 sm:px-5 ${topbarBg}`}>
          <button
            onClick={() => setMobileOpen(true)}
            className={iconBtn}
            aria-label="Open menu"
          >
            <IconMenu className="h-5 w-5" />
          </button>

          {/* Search: icon-only below 768px, full input above */}
          <div className="relative hidden max-w-md flex-1 md:block">
            <IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
            <input
              type="search"
              placeholder="Search products, alerts, bills…"
              aria-label="Search"
              className="h-10 w-full rounded-lg border border-white/[0.08] bg-white/[0.04] py-2 pl-10 pr-4 text-sm text-gray-100 placeholder-gray-500 focus:border-brand-500/60 focus:bg-white/[0.06] focus:outline-none focus:ring-1 focus:ring-brand-500/30"
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
            {/* Edge pill → icon-only below md */}
            <span
              className={`hidden items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium ring-1 ring-inset md:inline-flex ${
                status.edgeOnline
                  ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-300 ring-amber-500/25'
              }`}
            >
              {status.edgeOnline ? <IconWifi className="h-3.5 w-3.5" /> : <IconWifiOff className="h-3.5 w-3.5" />}
              {status.edgeOnline ? 'Edge connected' : 'Edge offline'}
            </span>
            <span
              className={`inline-flex h-10 w-10 items-center justify-center rounded-lg ring-1 ring-inset md:hidden ${
                status.edgeOnline
                  ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-300 ring-amber-500/25'
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
              <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-brand-400 ring-2 ring-[#0a0f1c]" />
            </button>

            <div className="ml-1 flex items-center gap-2.5 border-l border-white/[0.07] pl-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-bold text-white ring-1 ring-inset ring-white/15 shadow-soft">
                {initials}
              </span>
              <div className="hidden leading-tight lg:block">
                <p className="text-sm font-semibold text-gray-100">{session?.userName ?? 'Guest'}</p>
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
          <Outlet />
        </main>

        <footer className="flex items-center justify-between border-t border-white/[0.06] bg-[#0d1526] px-6 py-3 text-[11px] text-gray-500">
          <span>Storeye · Edge AI Retail Intelligence</span>
          <Link to="/app/settings" className="text-gray-500 hover:text-brand-400">
            v0.1.0 · offline-first
          </Link>
        </footer>
      </div>
    </div>
  )
}