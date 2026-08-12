import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authApi from '../api/auth'
import { FAKE_USER, TOKEN_KEY, apiError, renderApp } from './utils'

vi.mock('../api/auth')

describe('Login page', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders the sign-in form with labelled fields', async () => {
    renderApp('/login')

    expect(await screen.findByRole('heading', { name: /ai productivity agents/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('signs in and lands on the dashboard', async () => {
    const user = userEvent.setup()
    authApi.login.mockResolvedValue({ access_token: 'fake.jwt.value', expires_in: 3600 })
    authApi.getCurrentUser.mockResolvedValue(FAKE_USER)

    renderApp('/login')

    await user.type(await screen.findByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'a-good-passphrase')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    // Shown twice by design: in the sidebar and in the dashboard header.
    expect(screen.getAllByText(/user@example\.com/i).length).toBeGreaterThan(0)
  })

  it('maps AUTHENTICATION_FAILED to a friendly message', async () => {
    const user = userEvent.setup()
    authApi.login.mockRejectedValue(
      apiError('AUTHENTICATION_FAILED', 'Invalid email or password', { status: 401 }),
    )

    renderApp('/login')

    await user.type(await screen.findByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong-passphrase')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/invalid email or password/i)
  })

  it('never renders a raw traceback or internal detail', async () => {
    const user = userEvent.setup()
    authApi.login.mockRejectedValue(
      apiError('INTERNAL_SERVER_ERROR', 'Internal server error', { status: 500 }),
    )

    renderApp('/login')
    await user.type(await screen.findByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'a-good-passphrase')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).not.toMatch(/traceback|File "|site-packages/i)
  })

  it('validates empty fields before calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/login')

    await user.click(await screen.findByRole('button', { name: /sign in/i }))

    expect(await screen.findByText(/enter your email address/i)).toBeInTheDocument()
    expect(authApi.login).not.toHaveBeenCalled()
  })

  it('disables the submit button while signing in', async () => {
    const user = userEvent.setup()
    let resolveLogin
    authApi.login.mockReturnValue(new Promise((resolve) => { resolveLogin = resolve }))

    renderApp('/login')
    await user.type(await screen.findByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'a-good-passphrase')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    const button = screen.getByRole('button', { name: /signing in/i })
    expect(button).toBeDisabled()

    resolveLogin({ access_token: 'x', expires_in: 1 })
  })
})

describe('Register page', () => {
  beforeEach(() => localStorage.clear())

  it('renders all three fields', async () => {
    renderApp('/register')

    expect(await screen.findByRole('heading', { name: /create your account/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/^email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument()
  })

  it('rejects a short password client-side', async () => {
    const user = userEvent.setup()
    renderApp('/register')

    await user.type(await screen.findByLabelText(/^email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/^password/i), 'short')
    await user.type(screen.getByLabelText(/confirm password/i), 'short')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    // role="alert" distinguishes the validation error from the field hint,
    // which carries similar wording.
    const errors = await screen.findAllByRole('alert')
    expect(errors.some((node) => /at least 8 characters/i.test(node.textContent))).toBe(true)
    expect(authApi.register).not.toHaveBeenCalled()
  })

  it('rejects mismatched passwords', async () => {
    const user = userEvent.setup()
    renderApp('/register')

    await user.type(await screen.findByLabelText(/^email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/^password/i), 'a-good-passphrase')
    await user.type(screen.getByLabelText(/confirm password/i), 'a-different-one')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    const errors = await screen.findAllByRole('alert')
    expect(errors.some((node) => /passwords do not match/i.test(node.textContent))).toBe(true)
    expect(authApi.register).not.toHaveBeenCalled()
  })

  it('surfaces USER_ALREADY_EXISTS from the backend', async () => {
    const user = userEvent.setup()
    authApi.register.mockRejectedValue(
      apiError('USER_ALREADY_EXISTS', 'An account with this email already exists', {
        status: 409,
      }),
    )

    renderApp('/register')
    await user.type(await screen.findByLabelText(/^email/i), 'taken@example.com')
    await user.type(screen.getByLabelText(/^password/i), 'a-good-passphrase')
    await user.type(screen.getByLabelText(/confirm password/i), 'a-good-passphrase')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/i)
  })

  it('signs the user in on success', async () => {
    const user = userEvent.setup()
    authApi.register.mockResolvedValue(FAKE_USER)
    authApi.login.mockResolvedValue({ access_token: 'fake.jwt.value', expires_in: 3600 })
    authApi.getCurrentUser.mockResolvedValue(FAKE_USER)

    renderApp('/register')
    await user.type(await screen.findByLabelText(/^email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/^password/i), 'a-good-passphrase')
    await user.type(screen.getByLabelText(/confirm password/i), 'a-good-passphrase')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
  })
})

describe('session restoration', () => {
  it('shows a loading state instead of flashing the login page', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
    authApi.getCurrentUser.mockReturnValue(new Promise(() => {})) // never settles

    renderApp('/dashboard')

    expect(screen.getByText(/restoring your session/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
  })

  it('restores the user when the stored token is still valid', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
    authApi.getCurrentUser.mockResolvedValue(FAKE_USER)

    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
  })

  it('clears the session when the stored token is rejected', async () => {
    localStorage.setItem(TOKEN_KEY, 'expired.jwt.value')
    authApi.getCurrentUser.mockRejectedValue(
      apiError('TOKEN_EXPIRED', 'Authentication token has expired', { status: 401 }),
    )

    renderApp('/dashboard')

    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('does not call the API when no token is stored', async () => {
    renderApp('/dashboard')

    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(authApi.getCurrentUser).not.toHaveBeenCalled()
  })
})

describe('protected routes', () => {
  it.each(['/dashboard', '/content', '/developer', '/documents'])(
    'redirects %s to login when signed out',
    async (route) => {
      renderApp(route)

      expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    },
  )

  it('redirects a signed-in user away from /login', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
    authApi.getCurrentUser.mockResolvedValue(FAKE_USER)

    renderApp('/login')

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
  })

  it('shows a 404 page for an unknown route', async () => {
    renderApp('/nope')

    expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
  })
})

describe('logout', () => {
  it('clears the token and returns to the login page', async () => {
    const user = userEvent.setup()
    localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
    authApi.getCurrentUser.mockResolvedValue(FAKE_USER)

    renderApp('/dashboard')
    await screen.findByRole('heading', { name: /welcome back/i })

    await user.click(screen.getByRole('button', { name: /sign out/i }))

    await waitFor(() => expect(localStorage.getItem(TOKEN_KEY)).toBeNull())
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })
})
