import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Optional custom fallback; when omitted a branded default is shown. */
  fallback?: ReactNode
  /** Optional error hook (telemetry, logging). Never rethrows. */
  onError?: (error: Error, info: ErrorInfo) => void
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * M22 — top-level render guard.
 *
 * A render/runtime error inside one page must never blank the whole app (or
 * leave the shopkeeper staring at a white screen). This boundary shows the
 * error, explains that already-saved business data is unaffected, and offers a
 * retry + reload. It is deliberately dependency-free (class component).
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[Storeye] Unhandled UI error:', error, info)
    this.props.onError?.(error, info)
  }

  private reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) return this.props.fallback

    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
        <div className="w-full max-w-lg rounded-xl border border-red-500/30 bg-slate-900 p-6 text-slate-200">
          <h1 className="text-lg font-semibold text-red-300">
            Something went wrong on this screen
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Your saved inventory, sales and alerts are safe — they live on the local
            Edge Node, not in the browser. You can retry this screen or reload.
          </p>
          <pre className="mt-4 max-h-40 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-500">
            {error.message}
          </pre>
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={this.reset}
              className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
