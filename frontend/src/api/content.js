import { api } from './client'

/**
 * Content Agent endpoints.
 *
 * Field names mirror the backend Pydantic schemas exactly — nothing here is
 * invented. Text-producing tasks return { content, task_type, model, usage };
 * extract returns { entities, key_points, facts, keywords, ... }.
 */

export function generate(payload) {
  return api.post('/content/generate', payload)
}

export function summarize(text, summaryType) {
  return api.post('/content/summarize', { text, summary_type: summaryType })
}

export function rewrite(text, instructions) {
  return api.post('/content/rewrite', { text, instructions })
}

export function transformTone(text, tone) {
  return api.post('/content/tone', { text, tone })
}

export function adaptAudience(text, audience) {
  return api.post('/content/audience', { text, audience })
}

export function transformFormat(text, format) {
  return api.post('/content/format', { text, format })
}

export function extract(text) {
  return api.post('/content/extract', { text })
}
