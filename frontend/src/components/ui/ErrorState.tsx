import React from 'react'
import { NetworkError } from '../../lib/api/client'

function httpLabel(status: number): string {
  if (status === 404) return 'Not found'
  if (status === 422) return 'Validation error'
  if (status === 409) return 'Conflict'
  if (status === 401) return 'Unauthorized'
  if (status === 403) return 'Forbidden'
  if (status >= 500) return 'Server error'
  return `Error ${status}`
}

function describeError(err: unknown): { title: string; detail: string; isOffline: boolean } {
  if (err instanceof NetworkError) {
    return {
      title: 'Edge node unreachable',
      detail:
        'The local Storeye backend did not respond. Check that FastAPI (localhost:8000) is running. Stored data may still be visible below.',
      isOffline: true,
    }
  }
  if (err instanceof Error) {
    const status = (err as { status?: number }).status
    if (status) {
      return {
        title: httpLabel(status),
        detail: err.message,
        isOffline: false,
      }
    }
    return { title: 'Request failed', detail: err.message, isOffline: false }
  }
  return { title: 'Something went wrong', detail: String(err), isOffline: false }
}

export function ErrorMessage({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  compact?: boolean
}) {
  const { title, detail, isOffline } = describeError(error)
  if (compact) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
        <span className="font-medium">{title}:</span> {detail}
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-2 font-medium text-red-600 underline underline-offset-2 hover:text-red-800"
          >
            Retry
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="rounded-card border border-red-200 bg-red-50 p-6" role="alert">
      <div className="flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-red-500" aria-hidden="true" />
        <h3 className="text-base font-semibold text-red-700">{title}</h3>
      </div>
      <p className="mt-2 text-sm text-red-600">{detail}</p>
      {isOffline && (
        <p className="mt-1 text-xs text-red-400">
          Storeye is edge-first: this page still renders with whatever is cached.
        </p>
      )}
      {onRetry && (
        <button onClick={onRetry} className="btn-secondary mt-4">
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: React.ReactNode
}) {
  return (
    <div className="rounded-card border border-dashed border-gray-300 bg-gray-50 px-6 py-10 text-center">
      <p className="text-sm font-medium text-gray-500">{title}</p>
      {hint && <p className="mt-1 text-sm text-gray-400">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}