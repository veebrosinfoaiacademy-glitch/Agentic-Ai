import { api } from './client'

/** POST /api/auth/register → { id, email, created_at } */
export function register(email, password) {
  return api.post('/auth/register', { email, password })
}

/** POST /api/auth/login → { access_token, token_type, expires_in } */
export function login(email, password) {
  return api.post('/auth/login', { email, password })
}

/** GET /api/auth/me → { id, email, created_at } */
export function getCurrentUser() {
  return api.get('/auth/me')
}
