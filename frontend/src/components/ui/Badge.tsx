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
  gray: 'bg-white/[0.05] text-gray-500 ring-white/10',
  green: 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25',
  amber: 'bg-amber-500/10 text-amber-300 ring-amber-500/25',
  red: 'bg-red-500/10 text-red-300 ring-red-500/25',
  blue: 'bg-sky-500/10 text-sky-300 ring-sky-500/25',
  purple: 'bg-violet-500/10 text-violet-300 ring-violet-500/25',
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