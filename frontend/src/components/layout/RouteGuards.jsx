import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../../context/useAuth'
import { Spinner } from '../common'

function RestoringSession() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="flex items-center gap-3 text-slate-500">
        <Spinner />
        <span className="text-sm">Restoring your session…</span>
      </div>
    </div>
  )
}

/** Blocks a route until a user is known. */
export function RequireAuth({ children }) {
  const { isAuthenticated, isRestoring } = useAuth()
  const location = useLocation()

  // Wait for the token check rather than bouncing to /login and back, which
  // would flash the login form on every refresh.
  if (isRestoring) return <RestoringSession />

  if (!isAuthenticated) {
    // `state.from` lets login send the user back where they were heading.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return children
}

/** Keeps a signed-in user away from the login and register pages. */
export function RequireGuest({ children }) {
  const { isAuthenticated, isRestoring } = useAuth()

  if (isRestoring) return <RestoringSession />
  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  return children
}
