import React, { useEffect, useRef, useState } from 'react'

export function Card({
  children,
  className = '',
  title,
  subtitle,
  action,
}: {
  children: React.ReactNode
  className?: string
  title?: string
  subtitle?: string
  action?: React.ReactNode
}) {
  return (
    <section className={`card overflow-hidden ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-tight text-gray-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export type StatTone = 'default' | 'positive' | 'warning' | 'danger' | 'brand'

const valueTone: Record<StatTone, string> = {
  default: 'text-gray-900',
  positive: 'text-emerald-600',
  warning: 'text-amber-600',
  danger: 'text-red-600',
  brand: 'text-brand-700',
}

const chipTone: Record<StatTone, string> = {
  default: 'bg-gray-100 ring-gray-200',
  positive: 'bg-emerald-50 ring-emerald-200',
  warning: 'bg-amber-50 ring-amber-200',
  danger: 'bg-red-50 ring-red-200',
  brand: 'bg-brand-50 ring-brand-200',
}

function useCountUp(target: number, enabled: boolean): number {
  const [value, setValue] = useState(0)
  const frame = useRef<number>(0)
  useEffect(() => {
    if (!enabled) {
      setValue(target)
      return
    }
    const from = 0
    const start = performance.now()
    const dur = 520
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur)
      const eased = 1 - Math.pow(1 - p, 3)
      setValue(Math.round(from + (target - from) * eased))
      if (p < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [target, enabled])
  return value
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = 'default',
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon?: React.ReactNode
  tone?: StatTone
}) {
  const numeric = typeof value === 'number' && isFinite(value)
  const shown = useCountUp(
    numeric ? Number(value) : 0,
    numeric && Number(value) <= 1_000_000,
  )
  return (
    <div className="card card-hover p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-gray-500">{label}</p>
        {icon && (
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset ${chipTone[tone]}`}>
            {icon}
          </span>
        )}
      </div>
      <p className={`mt-1.5 text-2xl font-bold tracking-tight tabular ${valueTone[tone]}`}>
        {numeric ? shown.toLocaleString(value >= 1000 ? 'en-IN' : 'en-US') : value}
      </p>
      {hint && <p className="mt-0.5 truncate text-xs text-gray-500">{hint}</p>}
    </div>
  )
}

export const StatCard = Stat

export function PageHeader({
  eyebrow,
  title,
  description,
  trailing,
}: {
  eyebrow?: string
  title: React.ReactNode
  description?: React.ReactNode
  trailing?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{eyebrow}</p>
        )}
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="font-bold !text-black">{title}</h1>
        </div>
        {description && <p className="mt-1 text-sm text-black/70">{description}</p>}
      </div>
      {trailing && <div className="flex shrink-0 flex-wrap items-center gap-3">{trailing}</div>}
    </div>
  )
}