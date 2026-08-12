import axios from 'axios'

/**
 * The single Axios instance every API module uses.
 *
 * Two interceptors do the work that would otherwise be repeated in every
 * component: attaching the bearer token on the way out, and unwrapping the
 * backend's response envelope on the way back.
 */

// Only VITE_-prefixed variables reach the browser bundle. This is the one
// piece of configuration the frontend is allowed to know — never the Groq
// key, the Mongo URI or the JWT secret, all of which stay server-side.
const baseURL =
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_API_URL ??
  'http://localhost:8000/api'

export const TOKEN_STORAGE_KEY = 'apa.access_token'

export const api = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    // Private browsing modes can throw on storage access.
    return null
  }
}

export function setStoredToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token)
    else localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    /* storage unavailable — the in-memory session still works */
  }
}

/** Registered by AuthContext so a 401 anywhere can clear the session once. */
let onUnauthorized = null
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

api.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/**
 * A normalised error every page can render.
 *
 * The backend always answers with { success, message, error: { code, details } },
 * so we never fall back to reading FastAPI's default `detail` field.
 */
export class ApiError extends Error {
  constructor({ message, code, details, status, requestId }) {
    super(message)
    this.name = 'ApiError'
    this.code = code ?? 'UNKNOWN_ERROR'
    this.details = details ?? null
    this.status = status ?? 0
    // The server's correlation id, from the X-Request-ID response header.
    // Quoting it in a support request finds the exact server log lines.
    this.requestId = requestId ?? null
  }

  /** Seconds to wait before retrying, when the server said so. */
  get retryAfterSeconds() {
    const fromBody = this.details?.retry_after_seconds
    return typeof fromBody === 'number' && fromBody > 0 ? fromBody : null
  }

  /** Validation problems as { fieldName: message }, for inline form errors. */
  get fieldErrors() {
    if (this.code !== 'VALIDATION_ERROR' || !Array.isArray(this.details)) return {}
    return this.details.reduce((acc, item) => {
      if (item?.field) acc[item.field] = item.message
      return acc
    }, {})
  }
}

api.interceptors.response.use(
  // Unwrap the envelope so callers receive `data` directly.
  (response) => response.data?.data ?? response.data,
  (error) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data
    // Header names are case-insensitive in Axios's normalised headers.
    const requestId = error.response?.headers?.['x-request-id'] ?? null

    if (status === 401) {
      // Clear the session once. No retry — a stale token will never
      // spontaneously become valid, and retrying would loop.
      onUnauthorized?.()
    }

    if (body && typeof body === 'object' && body.error) {
      return Promise.reject(
        new ApiError({
          message: body.message,
          code: body.error.code,
          details: body.error.details,
          status,
          requestId,
        }),
      )
    }

    // Network failure, CORS rejection, or a non-envelope response.
    return Promise.reject(
      new ApiError({
        message:
          status === 0
            ? 'Could not reach the server. Check that the backend is running.'
            : 'Something went wrong. Please try again.',
        code: status === 0 ? 'NETWORK_ERROR' : 'UNEXPECTED_ERROR',
        status,
        requestId,
      }),
    )
  },
)
