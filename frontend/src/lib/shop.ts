// M28: shopkeeper-first business language.
//
// This is the single translation layer that turns internal Storeye concepts
// (alert enums, shelf states, inventory quantities, AI terminology) into the
// simple phrases a shopkeeper understands. Components/pages should prefer these
// helpers over raw enum strings so the UI never leaks internal vocabulary into
// the normal experience.

import type { AlertType, AlertSeverity } from './api/types'

/** "Good morning / afternoon / evening" based on local time. */
export function greeting(now: Date = new Date()): string {
  const h = now.getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

/** Indian-rupee formatting, e.g. ₹2,840. */
export function formatINR(value: number): string {
  const n = Number.isFinite(value) ? value : 0
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

export type StockStatus = 'GOOD' | 'LOW' | 'OUT'

export interface StockStatusInfo {
  status: StockStatus
  label: string
  /** Matches the Badge tone prop. */
  tone: 'green' | 'amber' | 'red'
  icon: string
}

/** Simple stock language: good / running low / out of stock. */
export function stockStatus(qty: number, reorderLevel = 0): StockStatusInfo {
  if (qty <= 0) return { status: 'OUT', label: 'Out of stock', tone: 'red', icon: '🔴' }
  if (qty <= Math.max(reorderLevel, 1)) return { status: 'LOW', label: 'Running low', tone: 'amber', icon: '🟡' }
  return { status: 'GOOD', label: 'Good stock', tone: 'green', icon: '🟢' }
}

/** Expiry bucket in shopkeeper words. */
export function expiryLabel(daysUntil: number): { label: string; tone: 'green' | 'amber' | 'red' } {
  if (daysUntil < 0) return { label: 'Expired', tone: 'red' }
  if (daysUntil <= 7) return { label: 'Expiring soon', tone: 'red' }
  if (daysUntil <= 30) return { label: 'Expires this month', tone: 'amber' }
  return { label: 'OK', tone: 'green' }
}

export type AlertCategory = 'STOCK' | 'EXPIRY' | 'SHELF' | 'CAMERA' | 'OTHER'

export const ALERT_CATEGORY_LABEL: Record<AlertCategory, string> = {
  STOCK: 'Stock',
  EXPIRY: 'Expiry',
  SHELF: 'Shelf',
  CAMERA: 'Camera',
  OTHER: 'Other',
}

/** Maps every internal alert enum to a shopkeeper category. */
export function alertCategory(alertType: AlertType): AlertCategory {
  switch (alertType) {
    case 'SHORTAGE':
    case 'SURPLUS':
      return 'STOCK'
    case 'EXPIRY':
      return 'EXPIRY'
    case 'LOW_SHELF_OCCUPANCY':
    case 'SHELF_EMPTY':
      return 'SHELF'
    case 'CAMERA_OFFLINE':
      return 'CAMERA'
    default:
      return 'OTHER'
  }
}

/** Shopkeeper wording for an alert type, hiding internal enums. */
export function alertTypeLabel(alertType: AlertType): string {
  switch (alertType) {
    case 'SHORTAGE':
      return 'Running low'
    case 'SURPLUS':
      return 'More stock than expected'
    case 'MISPLACEMENT':
      return 'On the wrong shelf'
    case 'EXPIRY':
      return 'Expiring soon'
    case 'LOW_SHELF_OCCUPANCY':
      return 'Shelf may need restocking'
    case 'SHELF_EMPTY':
      return 'Shelf needs restocking'
    case 'CAMERA_OFFLINE':
      return 'Camera needs attention'
    default:
      return 'Needs a review'
  }
}

export const ALERT_SEVERITY_LABEL: Record<AlertSeverity, string> = {
  INFO: 'Info',
  LOW: 'Low',
  MEDIUM: 'Medium',
  HIGH: 'High',
  CRITICAL: 'Urgent',
}

/** Plain-language copy for key empty states (M28 §31). */
export const EMPTY_COPY = {
  activity: 'No stock activity yet.',
  alerts: 'Nothing needs your attention right now.',
  stock: 'Your stock looks fine.',
  observations: 'No activity recorded yet.',
  receipts: 'No stock receipts waiting.',
  sales: 'No sales yet today.',
} as const

/** Plain-language copy for common errors (M28 §32). */
export const ERROR_COPY = {
  store: "We couldn't connect to the store service. Please check your connection.",
  generic: 'Something went wrong on our side. Please try again.',
  package: "We couldn't read this package. Please take a clearer photo.",
  form: 'Please check the details and try again.',
} as const

export function errorMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'message' in err && typeof (err as { message?: unknown }).message === 'string') {
    return (err as { message: string }).message
  }
  return ERROR_COPY.generic
}