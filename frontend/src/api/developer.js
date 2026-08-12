import { api } from './client'

/**
 * Developer Agent endpoints.
 *
 * Every response spreads its structured payload at the top level of `data`,
 * alongside task_type, model and usage.
 */

export function generateCode({ language, description, requirements }) {
  return api.post('/developer/generate', { language, description, requirements })
}

export function explainCode({ language, code }) {
  return api.post('/developer/explain', { language, code })
}

export function reviewCode({ language, code, reviewFocus }) {
  return api.post('/developer/review', { language, code, review_focus: reviewFocus })
}

export function refactorCode({ language, code, goals }) {
  return api.post('/developer/refactor', { language, code, goals })
}

export function generateTests({ language, code, framework }) {
  return api.post('/developer/tests', {
    language,
    code,
    // Omitted entirely when blank, so the backend picks the language default.
    ...(framework ? { framework } : {}),
  })
}

export function analyseBug({ language, code, errorMessage, context }) {
  return api.post('/developer/debug', {
    language,
    code,
    ...(errorMessage ? { error_message: errorMessage } : {}),
    ...(context ? { context } : {}),
  })
}

export function generateDocumentation({ language, code, documentationType }) {
  return api.post('/developer/document', {
    language,
    code,
    documentation_type: documentationType,
  })
}
