import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { Alert, Button, TextInput } from '../components/common'
import { useAuth } from '../context/useAuth'
import { friendlyError } from '../utils/errorMessages'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (isSubmitting) return

    setError(null)
    setFieldErrors({})

    if (!email.trim() || !password) {
      setFieldErrors({
        email: !email.trim() ? 'Enter your email address' : undefined,
        password: !password ? 'Enter your password' : undefined,
      })
      return
    }

    setIsSubmitting(true)
    try {
      await login(email.trim(), password)
      navigate(location.state?.from ?? '/dashboard', { replace: true })
    } catch (caught) {
      setFieldErrors(caught.fieldErrors ?? {})
      setError(friendlyError(caught))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold text-slate-900">AI Productivity Agents</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to continue</p>
        </div>

        <form
          onSubmit={handleSubmit}
          noValidate
          className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
        >
          {error && <Alert variant="error">{error}</Alert>}

          <TextInput
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            error={fieldErrors.email}
            placeholder="you@example.com"
          />

          <TextInput
            label="Password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={fieldErrors.password}
          />

          <Button type="submit" loading={isSubmitting} className="w-full">
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </Button>

          <p className="text-center text-sm text-slate-600">
            Don&apos;t have an account?{' '}
            <Link
              to="/register"
              className="font-medium text-indigo-600 underline-offset-2 hover:underline"
            >
              Create one
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
