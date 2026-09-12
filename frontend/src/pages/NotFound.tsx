import { Link } from 'react-router-dom'
import { IconAlert } from '../components/ui/icons'

export function NotFoundPage() {
  return (
    <div className="page-shell flex min-h-[60vh] flex-col items-center justify-center text-center">
      <span className="rounded-xl bg-gray-100 p-3">
        <IconAlert className="h-8 w-8 text-brand-600" />
      </span>
      <p className="mt-4 text-6xl font-black text-brand-700">404</p>
      <h1 className="mt-2 text-xl font-semibold">Page not found</h1>
      <p className="mt-1 max-w-md text-sm text-gray-500">
        The page you are looking for does not exist.
      </p>
      <Link
        to="/"
        className="btn-primary mt-4 px-4 py-2 text-sm"
      >
        Back to home
      </Link>
    </div>
  )
}