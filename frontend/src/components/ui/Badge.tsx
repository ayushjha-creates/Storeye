import React from 'react'

export type BadgeTone = 'gray' | 'green' | 'amber' | 'red' | 'blue' | 'purple'

const dots: Record<BadgeTone, string> = {
  gray: 'bg-gray-400',
  green: 'bg-emerald-400',
  amber: 'bg-amber-400',
  red: 'bg-red-400',
  blue: 'bg-sky-400',
  purple: 'bg-violet-400',
}

const tones: Record<BadgeTone, string> = {
  gray: 'bg-gray-100 text-gray-700 ring-gray-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
  purple: 'bg-violet-50 text-violet-700 ring-violet-200',
}

export function Badge({
  children,
  tone = 'gray',
}: {
  children: React.ReactNode
  tone?: BadgeTone
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium leading-5 ring-1 ring-inset ${tones[tone]}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dots[tone]}`} aria-hidden="true" />
      {children}
    </span>
  )
}

export function StatusPill({ ok, label }: { ok: boolean; label?: string }) {
  const tone = ok ? 'green' : 'red'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium leading-5 ring-1 ring-inset ${tones[tone]}`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`}
        aria-hidden="true"
      />
      {label ?? (ok ? 'Online' : 'Offline')}
    </span>
  )
}