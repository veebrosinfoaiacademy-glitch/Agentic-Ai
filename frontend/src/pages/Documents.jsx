import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { getSupportedTypes, uploadDocument } from '../api/documents'
import {
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ProseBlock,
} from '../components/common'
import { formatBytes, friendlyError, humanise } from '../utils/errorMessages'

export default function Documents() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  const [limits, setLimits] = useState(null)
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
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
        // Non-fatal: uploading still works, we just cannot show the rules.
        if (!cancelled) setLimits(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function selectFile(event) {
    const chosen = event.target.files?.[0] ?? null
    setFile(chosen)
    setResult(null)
    setError(null)

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
    setResult(null)
    setError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleUpload() {
    if (!file || isUploading) return
    setError(null)
    setIsUploading(true)
    try {
      setResult(await uploadDocument(file))
    } catch (caught) {
      setError(friendlyError(caught))
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Documents</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a document to extract its text. Files are processed in memory
          and are not stored.
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
              {/* min-w-0 + break-all so a very long filename wraps instead of
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

          {error && <Alert variant="error">{error}</Alert>}

          <Button onClick={handleUpload} loading={isUploading} disabled={!file}>
            {isUploading ? 'Extracting text…' : 'Upload and extract'}
          </Button>

          {limits?.ocr_supported === false && (
            <p className="text-xs text-slate-500">
              No OCR is performed, so scanned or image-only PDFs contain no
              extractable text.
            </p>
          )}
        </div>
      </Card>

      {result ? (
        <ExtractionResult
          result={result}
          onUseText={() => navigate('/content', { state: { text: result.text } })}
        />
      ) : (
        <Card title="Extracted text">
          <EmptyState
            title="Nothing extracted yet"
            description="Upload a document to see its text and metadata here."
          />
        </Card>
      )}
    </div>
  )
}

function ExtractionResult({ result, onUseText }) {
  // Whatever metadata the backend actually returned, rendered generically so
  // PDF page counts, DOCX table counts and CSV row counts all work.
  const metadata = Object.entries(result.metadata ?? {})

  return (
    <Card
      title="Extracted text"
      actions={
        <>
          <CopyButton text={result.text} />
          <Button variant="secondary" onClick={onUseText} className="px-3 py-1.5 text-xs">
            Use in Content Agent
          </Button>
        </>
      }
    >
      <dl className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="min-w-0">
          <dt className="text-xs text-slate-500">File</dt>
          <dd className="break-all text-sm font-medium text-slate-800">{result.filename}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Type</dt>
          <dd className="text-sm font-medium text-slate-800">{result.extension}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Size</dt>
          <dd className="text-sm font-medium text-slate-800">
            {formatBytes(result.size_bytes)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Characters</dt>
          <dd className="text-sm font-medium text-slate-800">
            {result.characters.toLocaleString()}
          </dd>
        </div>
      </dl>

      {metadata.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {metadata.map(([key, value]) => (
            <Badge key={key} tone="indigo">
              {humanise(key)}: {String(value)}
            </Badge>
          ))}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <ProseBlock text={result.text} />
      </div>
    </Card>
  )
}
