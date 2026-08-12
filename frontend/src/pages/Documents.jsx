import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { getSupportedTypes, listDocuments, uploadDocument } from '../api/documents'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Spinner,
} from '../components/common'
import { formatBytes, friendlyError, humanise } from '../utils/errorMessages'

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export default function Documents() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  const [limits, setLimits] = useState(null)
  const [documents, setDocuments] = useState([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)

  const [file, setFile] = useState(null)
  const [error, setError] = useState(null)
  const [errorRequestId, setErrorRequestId] = useState(null)
  const [isUploading, setIsUploading] = useState(false)

  // Limits come from the server so the UI cannot disagree with it about what
  // is accepted. Nothing here is hardcoded.
  useEffect(() => {
    let cancelled = false
    getSupportedTypes()
      .then((data) => {
        if (!cancelled) setLimits(data)
      })
      .catch(() => {
        if (!cancelled) setLimits(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const data = await listDocuments({ pageSize: 50 })
      setDocuments(data.documents)
      setTotal(data.total)
    } catch {
      // Non-fatal: uploading still works even if the list cannot load.
      setDocuments([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function selectFile(event) {
    const chosen = event.target.files?.[0] ?? null
    setFile(chosen)
    setError(null)
    setErrorRequestId(null)

    // A friendly early check. The backend remains authoritative — it also
    // verifies file signatures, which the browser cannot.
    if (chosen && limits) {
      const extension = `.${chosen.name.split('.').pop()?.toLowerCase() ?? ''}`
      if (!limits.extensions.includes(extension)) {
        setError(`That file type is not supported. Accepted: ${limits.extensions.join(', ')}`)
      } else if (chosen.size > limits.max_file_size_mb * 1024 * 1024) {
        setError(`That file is larger than the ${limits.max_file_size_mb} MB limit.`)
      }
    }
  }

  function clearSelection() {
    setFile(null)
    setError(null)
    setErrorRequestId(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleUpload() {
    if (!file || isUploading) return
    setError(null)
    setIsUploading(true)
    try {
      const stored = await uploadDocument(file)
      clearSelection()
      navigate(`/documents/${stored.id}`)
    } catch (caught) {
      setError(friendlyError(caught))
      setErrorRequestId(caught.requestId ?? null)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Documents</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a document to extract its text and keep it for later. Only you
          can see your documents.
        </p>
      </header>

      <Card
        title="Upload a document"
        description={
          limits
            ? `Accepted: ${limits.extensions.join(', ')} · up to ${limits.max_file_size_mb} MB`
            : 'Loading supported formats…'
        }
      >
        <div className="space-y-4">
          <div>
            <label
              htmlFor="document-file"
              className="block text-sm font-medium text-slate-700"
            >
              Choose a file
            </label>
            <input
              id="document-file"
              ref={fileInputRef}
              type="file"
              accept={limits?.extensions.join(',')}
              onChange={selectFile}
              className="mt-1.5 block w-full cursor-pointer rounded-lg border border-slate-300 text-sm text-slate-600 file:mr-3 file:cursor-pointer file:border-0 file:bg-slate-50 file:px-4 file:py-2.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
            />
          </div>

          {file && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-4 py-3">
              {/* min-w-0 + break-all so a long filename wraps rather than
                  stretching the card. */}
              <div className="min-w-0">
                <p className="break-all text-sm font-medium text-slate-800">{file.name}</p>
                <p className="text-xs text-slate-500">{formatBytes(file.size)}</p>
              </div>
              <Button variant="ghost" onClick={clearSelection} disabled={isUploading}>
                Remove
              </Button>
            </div>
          )}

          {error && (
            <Alert variant="error" requestId={errorRequestId}>
              {error}
            </Alert>
          )}

          <Button onClick={handleUpload} loading={isUploading} disabled={!file}>
            {isUploading ? 'Extracting text…' : 'Upload and extract'}
          </Button>

          {limits?.ocr_supported === false && (
            <p className="text-xs text-slate-500">
              No OCR is performed, so scanned or image-only PDFs contain no
              extractable text. The uploaded file itself is not stored — only
              the extracted text.
            </p>
          )}
        </div>
      </Card>

      <Card title={total ? `Your documents (${total})` : 'Your documents'}>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 py-10 text-slate-500">
            <Spinner />
            <span className="text-sm">Loading documents…</span>
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload one above to reuse its text in a conversation."
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {documents.map((document) => (
              <li key={document.id}>
                <Link
                  to={`/documents/${document.id}`}
                  className="flex items-center justify-between gap-4 py-3 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">
                      {document.title}
                    </p>
                    <p className="text-xs text-slate-500">
                      {formatBytes(document.size_bytes)} ·{' '}
                      {document.characters.toLocaleString()} characters ·{' '}
                      {formatDate(document.created_at)}
                    </p>
                  </div>
                  <Badge tone="indigo">{humanise(document.extension.slice(1))}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
