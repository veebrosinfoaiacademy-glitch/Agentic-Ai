import { useCallback, useEffect, useMemo, useState } from 'react'

import * as authApi from '../api/auth'
import { getStoredToken, setStoredToken, setUnauthorizedHandler } from '../api/client'
import { AuthContext } from './useAuth'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => getStoredToken())

  // Starts true so the app can show a splash instead of flashing the login
  // page while a stored token is being validated.
  const [isRestoring, setIsRestoring] = useState(true)

  const clearSession = useCallback(() => {
    setStoredToken(null)
    setToken(null)
    setUser(null)
  }, [])

  // Any 401 from any request clears the session exactly once. Registered here
  // rather than in the interceptor so the interceptor stays free of React.
  useEffect(() => {
    setUnauthorizedHandler(clearSession)
    return () => setUnauthorizedHandler(null)
  }, [clearSession])

  // On startup, a stored token is only a claim. Ask the backend whether it is
  // still valid rather than trusting it.
  useEffect(() => {
    let cancelled = false

    async function restore() {
      if (!getStoredToken()) {
        setIsRestoring(false)
        return
      }
      try {
        const me = await authApi.getCurrentUser()
        if (!cancelled) setUser(me)
      } catch {
        // Expired, revoked, or the account is gone. The interceptor has
        // already cleared storage; make sure local state agrees.
        if (!cancelled) clearSession()
      } finally {
        if (!cancelled) setIsRestoring(false)
      }
    }

    restore()
    return () => {
      cancelled = true
    }
  }, [clearSession])

  const login = useCallback(async (email, password) => {
    const { access_token: accessToken } = await authApi.login(email, password)
    setStoredToken(accessToken)
    setToken(accessToken)
    const me = await authApi.getCurrentUser()
    setUser(me)
    return me
  }, [])

  const register = useCallback(
    async (email, password) => {
      await authApi.register(email, password)
      // Sign in immediately — the simplest reliable flow, and it avoids
      // asking for the same credentials twice.
      return login(email, password)
    },
    [login],
  )

  const logout = useCallback(() => {
    // Access tokens are stateless, so signing out is discarding the token.
    // There is deliberately no server call to make.
    clearSession()
  }, [clearSession])

  const value = useMemo(
    () => ({
      user,
      token,
      isAuthenticated: Boolean(user),
      isRestoring,
      login,
      register,
      logout,
    }),
    [user, token, isRestoring, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
