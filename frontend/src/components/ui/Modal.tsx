import React, { useEffect } from 'react'

export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className={`card w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} p-5 shadow-lift`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-100">{title}</h2>
          <button
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-white/[0.06] hover:text-gray-200"
            aria-label="Close"
          >
            ✕
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function Button({
  children,
  onClick,
  kind = 'primary',
  type = 'button',
  disabled,
  className = '',
  title,
}: {
  children: React.ReactNode
  onClick?: () => void
  kind?: 'primary' | 'secondary' | 'danger' | 'ghost'
  type?: 'button' | 'submit'
  disabled?: boolean
  className?: string
  title?: string
}) {
  const kinds = {
    primary: 'bg-brand-600 text-white hover:bg-brand-500 disabled:bg-gray-300 disabled:text-gray-500',
    secondary:
      'bg-white/[0.04] text-gray-200 border border-white/10 hover:bg-white/[0.08] hover:text-white disabled:text-gray-500',
    danger: 'bg-red-600 text-white hover:bg-red-500 disabled:bg-gray-300 disabled:text-gray-500',
    ghost: 'text-brand-400 hover:bg-brand-500/10 hover:text-brand-300 disabled:text-gray-500',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200 disabled:cursor-not-allowed ${kinds[kind]} ${className}`}
    >
      {children}
    </button>
  )
}