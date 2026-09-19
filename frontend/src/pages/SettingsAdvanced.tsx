// M28: Settings → Advanced hub.
//
// The primary navigation is shopkeeper-first; the internal / technical AI
// screens still exist (backend + routes untouched) and are collected here for
// administrators and debugging. Nothing here changes the backend capabilities.

import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { useAuth } from '../auth/AuthContext'
import {
  IconActivity,
  IconBox,
  IconCamera,
  IconLightbulb,
  IconRefresh,
  IconRoute,
  IconShelf,
  IconSparkle,
  IconStore,
} from '../components/ui/icons'
import type { ReactNode } from 'react'

const LINKS: { to: string; title: string; description: string; icon: ReactNode }[] = [
  { to: '/app/product-intelligence', title: 'Stock activity', description: 'What the AI sees on your shelves, per product.', icon: <IconSparkle /> },
  { to: '/app/shelf-intelligence', title: 'Shelf configuration', description: 'Shelf areas and restocking suggestions.', icon: <IconShelf /> },
  { to: '/app/observations', title: 'AI diagnostics', description: 'Raw detections, confidence, camera health.', icon: <IconActivity /> },
  { to: '/app/reconciliation', title: 'Stock check', description: 'Camera activity vs your recorded stock.', icon: <IconRefresh /> },
  { to: '/app/journeys', title: 'Customer activity', description: 'Visitors and busy periods (no identity).', icon: <IconRoute /> },
  { to: '/app/insights', title: 'AI insights', description: 'Store insights that need a manual decision.', icon: <IconLightbulb /> },
  { to: '/app/live-store', title: 'Live store view', description: 'Real-time camera activity across the store.', icon: <IconStore /> },
]

export function SettingsAdvancedPage() {
  const { canManage } = useAuth()

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-gray-100 p-1.5">
          <IconBox className="h-4 w-4 text-brand-600" />
        </span>
        <div>
          <h1 className="font-bold">Advanced</h1>
          <p className="text-xs text-gray-500">Technical tools and store intelligence</p>
        </div>
      </div>

      {!canManage ? (
        <Card title="Restricted">
          <p className="text-sm text-gray-600">
            These tools are for the store owner or manager. Ask your store owner for access.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {LINKS.map((link) => (
            <Link key={link.to} to={link.to} className="card card-hover p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 ring-1 ring-inset ring-brand-100">
                  {link.icon}
                </span>
                <div>
                  <p className="text-sm font-semibold text-gray-900">{link.title}</p>
                  <p className="mt-0.5 text-xs text-gray-500">{link.description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      <div className="flex gap-3">
        <Link to="/app/settings" className="text-sm font-medium text-brand-600 hover:text-brand-700">
          ← Back to Settings
        </Link>
        <Link to="/app/cameras" className="text-sm font-medium text-brand-600 hover:text-brand-700">
          <span className="inline-flex items-center gap-1">
            <IconCamera className="h-4 w-4" /> Configure camera shelf areas
          </span>
        </Link>
      </div>
    </div>
  )
}