import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Alert, Button, TextInput } from '../components/common'
import { useAuth } from '../context/useAuth'
import { friendlyError } from '../utils/errorMessages'

// Matches the backend's rule exactly. Adding stricter client-side rules the
// server does not enforce would reject passwords the API would accept.
const MIN_PASSWORD_LENGTH = 8

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [form, setForm] = useState({ email: '', password: '', confirmPassword: '' })
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  function update(field) {
    return (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))
  }

  function validate() {
    const errors = {}
    if (!form.email.trim()) errors.email = 'Enter your email address'
    else if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) {
      errors.email = 'Enter a valid email address'
    }
    if (form.password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters`
    }
    if (form.confirmPassword !== form.password) {
      errors.confirmPassword = 'Passwords do not match'
    }
    return errors
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (isSubmitting) return

    setError(null)
    const errors = validate()
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setIsSubmitting(true)
    try {
      // register() signs in on success, so the user lands straight in the app.
      await register(form.email.trim(), form.password)
      navigate('/dashboard', { replace: true })
    } catch (caught) {
      // The backend stays authoritative — its field errors win over ours.
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
          <h1 className="text-xl font-semibold text-slate-900">Create your account</h1>
          <p className="mt-1 text-sm text-slate-500">
            Start using the content and developer agents
          </p>
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
            value={form.email}
            onChange={update('email')}
            error={fieldErrors.email}
            placeholder="you@example.com"
          />

          <TextInput
            label="Password"
            type="password"
            name="password"
            autoComplete="new-password"
            required
            hint={`At least ${MIN_PASSWORD_LENGTH} characters`}
            value={form.password}
            onChange={update('password')}
            error={fieldErrors.password}
          />

          <TextInput
            label="Confirm password"
            type="password"
            name="confirmPassword"
            autoComplete="new-password"
            required
            value={form.confirmPassword}
            onChange={update('confirmPassword')}
            error={fieldErrors.confirmPassword}
          />

          <Button type="submit" loading={isSubmitting} className="w-full">
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </Button>

          <p className="text-center text-sm text-slate-600">
            Already have an account?{' '}
            <Link
              to="/login"
              className="font-medium text-indigo-600 underline-offset-2 hover:underline"
            >
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
