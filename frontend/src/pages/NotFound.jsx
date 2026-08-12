import { Link } from 'react-router-dom'

import { useAuth } from '../context/useAuth'

export default function NotFound() {
  const { isAuthenticated } = useAuth()
  const destination = isAuthenticated ? '/dashboard' : '/login'

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 text-center">
      <p className="text-sm font-medium text-slate-400">404</p>
      <h1 className="mt-2 text-xl font-semibold text-slate-900">Page not found</h1>
      <p className="mt-1 text-sm text-slate-500">
        That page doesn&apos;t exist or has moved.
      </p>
      <Link
        to={destination}
        className="mt-6 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
      >
        {isAuthenticated ? 'Back to dashboard' : 'Go to sign in'}
      </Link>
    </div>
  )
}
