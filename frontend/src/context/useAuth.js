import { createContext, useContext } from 'react'

/**
 * The context object and its hook live apart from the provider component.
 *
 * React Fast Refresh only works when a module exports components alone, so
 * mixing `AuthProvider` and `useAuth` in one file breaks hot reloading.
 */
export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}
