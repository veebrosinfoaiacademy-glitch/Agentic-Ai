import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  api,
  getStoredToken,
  setStoredToken,
  setUnauthorizedHandler,
} from '../api/client'

/**
 * Exercises the real Axios interceptors.
 *
 * The page tests mock the api/* modules, which bypasses this layer entirely.
 * Phase 10 protects every agent route, so envelope unwrapping and the single
 * 401 path are now load-bearing and deserve direct coverage.
 *
 * A stub adapter replaces the network, so no server is required.
 */
function stubResponse({ status = 200, data }) {
  api.defaults.adapter = async (config) => {
    const response = { data, status, statusText: '', headers: {}, config }
    if (status >= 200 && status < 300) return response
    const error = new Error(`Request failed with status ${status}`)
    error.response = response
    error.config = config
    throw error
  }
}

function stubNetworkFailure() {
  api.defaults.adapter = async () => {
    throw new Error('Network Error') // no `response` — a genuine network failure
  }
}

beforeEach(() => {
  setUnauthorizedHandler(null)
  localStorage.clear()
})

describe('request interceptor', () => {
  it('attaches the stored token as a Bearer header', async () => {
    setStoredToken('stored.jwt.value')
    let seen = null
    api.defaults.adapter = async (config) => {
      seen = config.headers.Authorization
      return { data: { success: true, data: {} }, status: 200, headers: {}, config }
    }

    await api.get('/anything')

    expect(seen).toBe('Bearer stored.jwt.value')
  })

  it('sends no Authorization header when signed out', async () => {
    let seen = 'unset'
    api.defaults.adapter = async (config) => {
      seen = config.headers.Authorization
      return { data: { success: true, data: {} }, status: 200, headers: {}, config }
    }

    await api.get('/anything')

    expect(seen).toBeUndefined()
  })
})

describe('response interceptor', () => {
  it('unwraps the backend envelope so callers receive `data`', async () => {
    stubResponse({
      data: { success: true, message: 'ok', data: { content: 'generated' } },
    })

    await expect(api.post('/content/generate')).resolves.toEqual({
      content: 'generated',
    })
  })

  it('converts an error envelope into a typed ApiError', async () => {
    stubResponse({
      status: 429,
      data: {
        success: false,
        message: 'AI service rate limit reached.',
        error: { code: 'AI_RATE_LIMITED', details: null },
      },
    })

    const error = await api.post('/content/generate').catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('AI_RATE_LIMITED')
    expect(error.status).toBe(429)
  })

  it('exposes validation details as per-field messages', async () => {
    stubResponse({
      status: 422,
      data: {
        success: false,
        message: 'Invalid request data',
        error: {
          code: 'VALIDATION_ERROR',
          details: [{ field: 'text', message: 'String should have at least 1 character' }],
        },
      },
    })

    const error = await api.post('/content/summarize').catch((caught) => caught)

    expect(error.fieldErrors).toEqual({
      text: 'String should have at least 1 character',
    })
  })

  it('reports a network failure without inventing a backend code', async () => {
    stubNetworkFailure()

    const error = await api.get('/health').catch((caught) => caught)

    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.message).toMatch(/could not reach the server/i)
  })
})

describe('401 handling', () => {
  it('clears the session exactly once and does not retry', async () => {
    setStoredToken('expired.jwt.value')
    const onUnauthorized = vi.fn(() => setStoredToken(null))
    setUnauthorizedHandler(onUnauthorized)

    let requestCount = 0
    api.defaults.adapter = async (config) => {
      requestCount += 1
      const response = {
        data: {
          success: false,
          message: 'Authentication token has expired',
          error: { code: 'TOKEN_EXPIRED', details: null },
        },
        status: 401,
        headers: {},
        config,
      }
      const error = new Error('Unauthorized')
      error.response = response
      throw error
    }

    const error = await api.post('/content/generate').catch((caught) => caught)

    expect(error.code).toBe('TOKEN_EXPIRED')
    // One 401 → one logout, and no automatic retry loop.
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(requestCount).toBe(1)
    expect(getStoredToken()).toBeNull()
  })

  it.each(['TOKEN_MISSING', 'TOKEN_INVALID', 'TOKEN_EXPIRED', 'USER_NOT_FOUND'])(
    'treats %s from a protected route as a session failure',
    async (code) => {
      const onUnauthorized = vi.fn()
      setUnauthorizedHandler(onUnauthorized)
      stubResponse({
        status: 401,
        data: { success: false, message: 'nope', error: { code, details: null } },
      })

      const error = await api.post('/developer/explain').catch((caught) => caught)

      expect(error.code).toBe(code)
      expect(onUnauthorized).toHaveBeenCalledTimes(1)
    },
  )

  it('does not clear the session for non-401 failures', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    stubResponse({
      status: 502,
      data: {
        success: false,
        message: 'AI service is temporarily unavailable',
        error: { code: 'AI_PROVIDER_ERROR', details: null },
      },
    })

    await api.post('/content/generate').catch(() => {})

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

describe('configuration safety', () => {
  it('reads only the public API base URL from the environment', () => {
    // Anything sensitive would have to be a VITE_ variable to reach the
    // browser, and none exists.
    const exposed = Object.keys(import.meta.env).filter((key) => key.startsWith('VITE_'))

    expect(exposed).toEqual(expect.arrayContaining(['VITE_API_BASE_URL']))
    for (const key of exposed) {
      expect(key).not.toMatch(/GROQ|MONGO|JWT|SECRET|PASSWORD/i)
    }
  })

  it('points at the backend, not at a provider', () => {
    expect(api.defaults.baseURL).not.toMatch(/groq\.com|mongodb/i)
  })
})
