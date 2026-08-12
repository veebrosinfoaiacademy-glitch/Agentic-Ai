import { api } from './client'

/**
 * Conversation endpoints.
 *
 * Every call is authenticated by the shared Axios client's bearer
 * interceptor — there is no second client and no per-call token handling.
 * The server derives ownership from that token, so nothing here sends a
 * user id.
 */

/** POST /api/conversations */
export function createConversation(title, agentType) {
  return api.post('/conversations', { title, agent_type: agentType })
}

/** GET /api/conversations → { conversations, page, page_size, total, has_more } */
export function listConversations({ page = 1, pageSize = 20 } = {}) {
  return api.get('/conversations', { params: { page, page_size: pageSize } })
}

/** GET /api/conversations/{id} → conversation plus its messages */
export function getConversation(conversationId) {
  return api.get(`/conversations/${conversationId}`)
}

/** PATCH /api/conversations/{id} — title is the only mutable field */
export function renameConversation(conversationId, title) {
  return api.patch(`/conversations/${conversationId}`, { title })
}

/** DELETE /api/conversations/{id} — removes the conversation and its messages */
export function deleteConversation(conversationId) {
  return api.delete(`/conversations/${conversationId}`)
}

/**
 * POST /api/conversations/{id}/messages
 *
 * `options` is optional; every field defaults to the same value the matching
 * direct endpoint uses, so `{ taskType, prompt }` alone is a valid request.
 */
export function sendMessage(conversationId, { taskType, prompt, options }) {
  return api.post(`/conversations/${conversationId}/messages`, {
    task_type: taskType,
    prompt,
    ...(options ? { options } : {}),
  })
}

/** Tasks each agent supports, mirroring the backend's TASKS_BY_AGENT. */
export const TASKS_BY_AGENT = {
  content: ['generate', 'summarize', 'rewrite', 'tone', 'audience', 'format', 'extract'],
  developer: ['generate', 'explain', 'review', 'refactor', 'tests', 'debug', 'document'],
}
