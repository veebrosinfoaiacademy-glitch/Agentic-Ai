import { useId, useState } from 'react'

/**
 * Shared primitives.
 *
 * Kept in one small file rather than scattered across a dozen one-component
 * modules — it is easier to keep the visual language consistent when the
 * pieces sit next to each other.
 */

/* --- Buttons ------------------------------------------------------------ */

const BUTTON_VARIANTS = {
  primary:
    'bg-indigo-600 text-white hover:bg-indigo-700 focus-visible:outline-indigo-600 disabled:bg-indigo-300',
  secondary:
    'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 focus-visible:outline-slate-500 disabled:text-slate-400',
  ghost:
    'text-slate-600 hover:bg-slate-100 focus-visible:outline-slate-500 disabled:text-slate-400',
  danger:
    'bg-white text-red-700 ring-1 ring-inset ring-red-300 hover:bg-red-50 focus-visible:outline-red-600',
}

export function Button({
  children,
  variant = 'primary',
  loading = false,
  disabled = false,
  className = '',
  type = 'button',
  ...props
}) {
  const isDisabled = disabled || loading
  return (
    <button
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  )
}

export function Spinner({ className = 'h-5 w-5' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
        fill="none"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"
      />
    </svg>
  )
}

/* --- Form controls ------------------------------------------------------ */

function FieldShell({ label, hint, error, required, htmlFor, children }) {
  const errorId = `${htmlFor}-error`
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-red-600" aria-hidden="true">*</span>}
      </label>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
      <div className="mt-1.5">{children}</div>
      {/* role="alert" so screen readers announce the problem, and the text
          itself names the issue — colour alone is never the only signal. */}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}

const CONTROL_CLASSES =
  'block w-full rounded-lg border-0 px-3 py-2 text-slate-900 shadow-sm ring-1 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 disabled:bg-slate-50 disabled:text-slate-500 sm:text-sm'

export function TextInput({ label, hint, error, required, ...props }) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} htmlFor={id}>
      <input
        id={id}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`${CONTROL_CLASSES} ${error ? 'ring-red-400' : 'ring-slate-300'}`}
        {...props}
      />
    </FieldShell>
  )
}

export function TextArea({ label, hint, error, required, rows = 8, mono = false, ...props }) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} htmlFor={id}>
      <textarea
        id={id}
        rows={rows}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`${CONTROL_CLASSES} resize-y ${mono ? 'font-mono text-[13px] leading-relaxed' : ''} ${error ? 'ring-red-400' : 'ring-slate-300'}`}
        {...props}
      />
    </FieldShell>
  )
}

export function Select({ label, hint, error, options, required, ...props }) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} htmlFor={id}>
      <select
        id={id}
        aria-invalid={error ? 'true' : undefined}
        className={`${CONTROL_CLASSES} bg-white ${error ? 'ring-red-400' : 'ring-slate-300'}`}
        {...props}
      >
        {options.map(({ value, label: optionLabel }) => (
          <option key={value} value={value}>
            {optionLabel}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}

export function CheckboxGroup({ legend, options, selected, onToggle }) {
  return (
    <fieldset>
      <legend className="text-sm font-medium text-slate-700">{legend}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map(({ value, label }) => {
          const isChecked = selected.includes(value)
          return (
            <label
              key={value}
              className={`cursor-pointer rounded-full px-3 py-1.5 text-sm ring-1 ring-inset transition-colors focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-indigo-600 ${
                isChecked
                  ? 'bg-indigo-50 text-indigo-800 ring-indigo-300'
                  : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'
              }`}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={isChecked}
                onChange={() => onToggle(value)}
              />
              {/* A check mark, not just a colour change. */}
              {isChecked && <span aria-hidden="true">✓ </span>}
              {label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

/* --- Surfaces ----------------------------------------------------------- */

export function Card({ title, description, actions, children, className = '' }) {
  return (
    <section
      className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

const ALERT_STYLES = {
  error: 'bg-red-50 text-red-800 ring-red-200',
  success: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  info: 'bg-sky-50 text-sky-800 ring-sky-200',
  warning: 'bg-amber-50 text-amber-900 ring-amber-200',
}

const ALERT_PREFIX = {
  error: 'Error',
  success: 'Success',
  info: 'Note',
  warning: 'Warning',
}

export function Alert({ variant = 'info', title, children, requestId }) {
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={`rounded-lg px-4 py-3 text-sm ring-1 ring-inset ${ALERT_STYLES[variant]}`}
    >
      {/* The prefix means the meaning survives without colour. */}
      <p className="font-medium">{title ?? ALERT_PREFIX[variant]}</p>
      {children && <div className="mt-1 leading-relaxed">{children}</div>}
      {/* The server's correlation id. Shown only on failures, and only so a
          user can quote it when reporting the problem. */}
      {requestId && (
        <p className="mt-2 font-mono text-xs opacity-75">
          Reference: {requestId}
        </p>
      )}
    </div>
  )
}

export function EmptyState({ title, description, icon = '✦' }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 px-6 py-12 text-center">
      <span aria-hidden="true" className="text-2xl text-slate-300">
        {icon}
      </span>
      <p className="mt-3 text-sm font-medium text-slate-700">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
    </div>
  )
}

export function Badge({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700',
    red: 'bg-red-100 text-red-800',
    orange: 'bg-orange-100 text-orange-800',
    amber: 'bg-amber-100 text-amber-900',
    sky: 'bg-sky-100 text-sky-800',
    emerald: 'bg-emerald-100 text-emerald-800',
    indigo: 'bg-indigo-100 text-indigo-800',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

/* --- Output ------------------------------------------------------------- */

export function CopyButton({ text, label = 'Copy' }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Older browsers and insecure origins have no clipboard API.
      return
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <Button variant="secondary" onClick={handleCopy} className="px-3 py-1.5 text-xs">
      {/* aria-live so the confirmation is announced, not just seen. */}
      <span aria-live="polite">{copied ? 'Copied' : label}</span>
    </Button>
  )
}

/** Long AI output must scroll inside its own box, never widen the page. */
export function CodeBlock({ code, label }) {
  if (!code) return null
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      {label && (
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-1.5">
          <span className="text-xs font-medium text-slate-600">{label}</span>
          <CopyButton text={code} />
        </div>
      )}
      <pre className="max-h-96 overflow-auto bg-slate-50 p-4 text-[13px] leading-relaxed">
        <code className="font-mono text-slate-800">{code}</code>
      </pre>
    </div>
  )
}

export function ProseBlock({ text }) {
  if (!text) return null
  return (
    <div className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800">
      {text}
    </div>
  )
}

export function BulletList({ items, empty = null }) {
  if (!items?.length) return empty
  return (
    <ul className="space-y-1.5 text-sm text-slate-700">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2">
          <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  )
}

/** task_type / model / token usage, shown quietly. */
export function ResultMeta({ result }) {
  if (!result) return null
  const parts = []
  if (result.task_type) parts.push(result.task_type.replace(/_/g, ' '))
  if (result.model) parts.push(result.model)
  if (result.usage?.total_tokens) parts.push(`${result.usage.total_tokens} tokens`)
  if (!parts.length) return null

  return (
    <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-400">
      {parts.join(' · ')}
    </p>
  )
}
