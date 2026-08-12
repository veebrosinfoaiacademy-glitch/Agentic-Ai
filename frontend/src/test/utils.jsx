import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import App from '../App'
import { AuthProvider } from '../context/AuthContext'

/** Render the whole app at a given route, so routing and guards are exercised. */
export function renderApp(route = '/') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  )
}

/** Render one component inside the providers it needs. */
export function renderWithProviders(ui, route = '/') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  )
}

export const TOKEN_KEY = 'apa.access_token'

export const FAKE_USER = {
  id: '507f1f77bcf86cd799439011',
  email: 'user@example.com',
  created_at: '2026-01-01T00:00:00Z',
}

/** Build the ApiError shape the client interceptor produces. */
export function apiError(
  code,
  message,
  { status = 400, details = null, requestId = null } = {},
) {
  const error = new Error(message)
  error.name = 'ApiError'
  error.code = code
  error.details = details
  error.status = status
  // The X-Request-ID the real client copies off the response, so tests can
  // assert it reaches the UI.
  error.requestId = requestId
  Object.defineProperty(error, 'fieldErrors', {
    get() {
      if (code !== 'VALIDATION_ERROR' || !Array.isArray(details)) return {}
      return details.reduce((acc, item) => {
        if (item?.field) acc[item.field] = item.message
        return acc
      }, {})
    },
  })
  return error
}
