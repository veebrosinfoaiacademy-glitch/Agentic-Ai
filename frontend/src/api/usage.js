import { api } from './client'

/**
 * GET /api/usage
 * → { hour: {used, limit, remaining, resets_at}, day: {...}, limited }
 *
 * Uses the shared Axios instance, so the bearer token is attached by the same
 * interceptor as every other call. The server derives identity from that
 * token; nothing here sends a user id.
 *
 * A `limit` of 0 means the window is unlimited and `remaining` is null.
 */
export function getUsage() {
  return api.get('/usage')
}
