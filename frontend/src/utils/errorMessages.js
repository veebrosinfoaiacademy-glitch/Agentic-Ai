/**
 * Backend error codes translated into something a user can act on.
 *
 * The backend already refuses to leak stack traces, keys or connection
 * strings; this layer makes what it does return readable. Anything not
 * listed falls back to the backend's own message, which is always safe.
 */
const MESSAGES = {
  // Authentication
  AUTHENTICATION_FAILED: 'Invalid email or password.',
  TOKEN_MISSING: 'Please sign in to continue.',
  TOKEN_INVALID: 'Your session is no longer valid. Please sign in again.',
  TOKEN_EXPIRED: 'Your session has expired. Please sign in again.',
  USER_ALREADY_EXISTS: 'An account with this email already exists.',
  USER_NOT_FOUND: 'Your session is no longer valid. Please sign in again.',
  AUTH_NOT_CONFIGURED:
    'Authentication is not configured on the server. Contact the administrator.',

  // AI provider
  AI_NOT_CONFIGURED: 'The AI service is not configured on the server.',
  AI_RATE_LIMITED:
    'The AI service is temporarily rate limited. Please try again shortly.',
  AI_PROVIDER_TIMEOUT: 'The AI service took too long to respond. Please try again.',
  AI_PROVIDER_ERROR: 'The AI service is temporarily unavailable. Please try again.',
  AI_MODEL_UNAVAILABLE: 'The configured AI model is unavailable.',
  AI_INVALID_OUTPUT: 'The AI returned an invalid result. Please try again.',
  AI_EMPTY_RESPONSE: 'The AI returned an empty response. Please try again.',

  // Documents
  DOCUMENT_TOO_LARGE: 'That file is too large.',
  DOCUMENT_CONTENT_TOO_LARGE:
    'That document contains more text than can be processed.',
  DOCUMENT_TYPE_NOT_SUPPORTED: 'That file type is not supported.',
  DOCUMENT_INVALID: 'That file could not be read. It may be corrupt.',
  DOCUMENT_TEXT_NOT_FOUND:
    'No readable text was found. Scanned or image-only files are not supported.',
  DOCUMENT_EXTRACTION_FAILED: 'That document could not be processed.',

  // Usage limits (ours, not the provider's)
  USAGE_LIMIT_EXCEEDED:
    'You have reached your AI usage limit. Please try again after it resets.',

  // Infrastructure
  DATABASE_UNAVAILABLE: 'The service is temporarily unavailable. Please try again.',
  DATABASE_NOT_CONFIGURED: 'The database is not configured on the server.',
  VALIDATION_ERROR: 'Please check the highlighted fields.',
  NETWORK_ERROR: 'Could not reach the server. Check that the backend is running.',
  INTERNAL_SERVER_ERROR: 'Something went wrong on the server. Please try again.',
}

export function friendlyError(error) {
  if (!error) return 'Something went wrong.'
  return MESSAGES[error.code] ?? error.message ?? 'Something went wrong.'
}

/** Human labels for the enum values the backend accepts. */
export function humanise(value) {
  if (!value) return ''
  return String(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** "in 42 minutes" / "in 3 hours", for quota reset messaging. */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'shortly'
  if (seconds < 60) return `in ${Math.ceil(seconds)} seconds`
  if (seconds < 3600) return `in ${Math.ceil(seconds / 60)} minutes`
  const hours = Math.round(seconds / 3600)
  return `in ${hours} hour${hours === 1 ? '' : 's'}`
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
