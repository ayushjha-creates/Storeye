export function Spinner({
  className = '',
  label = 'Loading…',
}: {
  className?: string
  label?: string
}) {
  return (
    <div className={`flex items-center justify-center py-8 ${className}`} role="status">
      <svg
        className="h-6 w-6 animate-spin text-brand-600"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <span className="ml-3 text-sm text-gray-500">{label}</span>
    </div>
  )
}