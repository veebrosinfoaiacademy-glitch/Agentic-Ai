import { api } from './client'

/**
 * GET /api/documents/supported-types
 * → { extensions, max_file_size_mb, max_extracted_characters, ocr_supported }
 *
 * Fetched rather than hardcoded so the UI cannot disagree with the server
 * about what it accepts.
 */
export function getSupportedTypes() {
  return api.get('/documents/supported-types')
}

/**
 * POST /api/documents/upload (multipart)
 * → { filename, extension, content_type, size_bytes, characters, text, metadata }
 */
export function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/documents/upload', formData, {
    // Let the browser set the multipart boundary; a manual value breaks it.
    headers: { 'Content-Type': undefined },
  })
}
