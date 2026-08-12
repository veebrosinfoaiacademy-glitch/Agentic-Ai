import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, setUnauthorizedHandler } from '../api/client'
import * as authApi from '../api/auth'
import * as contentApi from '../api/content'
import * as conversationsApi from '../api/conversations'
import * as documentsApi from '../api/documents'
import * as usageApi from '../api/usage'
import { formatDuration, friendlyError } from '../utils/errorMessages'
import { FAKE_USER, TOKEN_KEY, apiError, renderApp } from './utils'

vi.mock('../api/auth')
vi.mock('../api/content')
vi.mock('../api/conversations')
vi.mock('../api/documents')
vi.mock('../api/usage')

const USAGE = {
  hour: {
    used: 3,
    limit: 100,
    remaining: 97,
    resets_at: new Date(Date.now() + 30 * 60_000).toISOString(),
  },
  day: {
    used: 12,
    limit: 500,
    remaining: 488,
    resets_at: new Date(Date.now() + 6 * 3600_000).toISOString(),
  },
  limited: true,
}

beforeEach(() => {
  localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
  authApi.getCurrentUser.mockResolvedValue(FAKE_USER)
  conversationsApi.listConversations.mockResolvedValue({
    conversations: [], page: 1, page_size: 5, total: 0, has_more: false,
  })
  documentsApi.getSupportedTypes.mockResolvedValue({
    extensions: ['.txt'], max_file_size_mb: 10, max_extracted_characters: 100000,
    ocr_supported: false,
  })
  usageApi.getUsage.mockResolvedValue(USAGE)
})

describe('usage meter', () => {
  it('shows real counts against the configured limits', async () => {
    renderApp('/dashboard')

    // The card heading renders while loading, so wait for the numbers
    // themselves rather than asserting synchronously after the heading.
    expect(await screen.findByText('3 / 100')).toBeInTheDocument()
    expect(screen.getByText('12 / 500')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /ai usage/i })).toBeInTheDocument()
    expect(usageApi.getUsage).toHaveBeenCalled()
  })

  it('exposes progress accessibly, not by colour alone', async () => {
    renderApp('/dashboard')

    const bars = await screen.findAllByRole('progressbar')
    expect(bars[0]).toHaveAttribute('aria-valuenow', '3')
    expect(bars[0]).toHaveAttribute('aria-valuemax', '100')
    expect(bars[0]).toHaveAccessibleName(/3 of 100 requests used/i)
  })

  it('shows a loading state while usage is fetched', async () => {
    usageApi.getUsage.mockReturnValue(new Promise(() => {}))

    renderApp('/dashboard')

    expect(await screen.findByText(/loading usage/i)).toBeInTheDocument()
  })

  it('reports unavailability rather than a reassuring zero', async () => {
    usageApi.getUsage.mockRejectedValue(
      apiError('DATABASE_UNAVAILABLE', 'unavailable', { status: 503 }),
    )

    renderApp('/dashboard')

    expect(await screen.findByText(/usage unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/requests are unaffected/i)).toBeInTheDocument()
  })

  it('says "Unlimited" when no limit is configured', async () => {
    usageApi.getUsage.mockResolvedValue({
      hour: { used: 7, limit: 0, remaining: null, resets_at: USAGE.hour.resets_at },
      day: { used: 7, limit: 0, remaining: null, resets_at: USAGE.day.resets_at },
      limited: false,
    })

    renderApp('/dashboard')

    expect(await screen.findAllByText(/unlimited/i)).toHaveLength(2)
    expect(screen.getByText(/no usage limits are configured/i)).toBeInTheDocument()
    // A bar would imply a ceiling that does not exist.
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('shows when the window resets', async () => {
    renderApp('/dashboard')

    expect(await screen.findByText(/resets in 30 min/i)).toBeInTheDocument()
  })
})

describe('429 handling', () => {
  it('maps USAGE_LIMIT_EXCEEDED to a readable message', () => {
    const error = apiError('USAGE_LIMIT_EXCEEDED', 'limit reached', { status: 429 })

    expect(friendlyError(error)).toMatch(/reached your ai usage limit/i)
  })

  it('shows the limit message when an AI request is refused', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockRejectedValue(
      apiError('USAGE_LIMIT_EXCEEDED', 'limit reached', {
        status: 429,
        details: { window: 'hour', limit: 100, retry_after_seconds: 1800 },
      }),
    )

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'AI in education')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai usage limit/i)
  })

  it('reads retry-after from the error details', () => {
    const error = new ApiError({
      code: 'USAGE_LIMIT_EXCEEDED',
      message: 'x',
      status: 429,
      details: { retry_after_seconds: 900 },
    })

    expect(error.retryAfterSeconds).toBe(900)
    expect(formatDuration(900)).toBe('in 15 minutes')
  })

  it('reports no retry hint when the server gave none', () => {
    const error = new ApiError({ code: 'AI_PROVIDER_ERROR', message: 'x', status: 502 })

    expect(error.retryAfterSeconds).toBeNull()
  })
})

describe('request correlation ids', () => {
  beforeEach(() => {
    setUnauthorizedHandler(null)
  })

  it('captures X-Request-ID from a failed response', async () => {
    api.defaults.adapter = async (config) => {
      const response = {
        data: {
          success: false,
          message: 'Something went wrong on the server.',
          error: { code: 'INTERNAL_SERVER_ERROR', details: null },
        },
        status: 500,
        headers: { 'x-request-id': 'abc123def456' },
        config,
      }
      const failure = new Error('Server error')
      failure.response = response
      throw failure
    }

    const error = await api.post('/content/generate').catch((caught) => caught)

    expect(error.requestId).toBe('abc123def456')
  })

  it('leaves requestId null when the server sent none', async () => {
    api.defaults.adapter = async (config) => {
      const response = {
        data: { success: false, message: 'x', error: { code: 'BAD', details: null } },
        status: 400,
        headers: {},
        config,
      }
      const failure = new Error('Bad request')
      failure.response = response
      throw failure
    }

    const error = await api.get('/anything').catch((caught) => caught)

    expect(error.requestId).toBeNull()
  })

  it('surfaces the reference on screen so a user can quote it', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockRejectedValue(
      apiError('INTERNAL_SERVER_ERROR', 'Something went wrong', {
        status: 500,
        requestId: 'trace9876543210',
      }),
    )

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'AI')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/reference: trace9876543210/i)
  })

  it('shows no reference line when there is no id', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockRejectedValue(
      apiError('AI_PROVIDER_ERROR', 'unavailable', { status: 502 }),
    )

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'AI')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).not.toHaveTextContent(/reference:/i)
  })
})

describe('no regression in session handling', () => {
  it('still restores a session and shows the dashboard', async () => {
    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
  })

  it('still redirects to login when signed out', async () => {
    localStorage.clear()

    renderApp('/dashboard')

    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(usageApi.getUsage).not.toHaveBeenCalled()
  })

  it('does not send provider secrets through VITE variables', () => {
    for (const key of Object.keys(import.meta.env)) {
      if (key.startsWith('VITE_')) {
        expect(key).not.toMatch(/GROQ|MONGO|JWT|SECRET|PASSWORD/i)
      }
    }
  })
})
