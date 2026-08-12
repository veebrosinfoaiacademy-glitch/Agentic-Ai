import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  deleteDocument,
  getDocument,
  renameDocument,
} from '../api/documents'
import {
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  ProseBlock,
  Spinner,
  TextInput,
} from '../components/common'
import { formatBytes, friendlyError, humanise } from '../utils/errorMessages'

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export default function DocumentDetail() {
  const { documentId } = useParams()
  const navigate = useNavigate()

  const [document, setDocument] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  const [isRenaming, setIsRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [actionError, setActionError] = useState(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const data = await getDocument(documentId)
      setDocument(data)
      setDraftTitle(data.title)
    } catch (caught) {
      setLoadError(friendlyError(caught))
    } finally {
      setIsLoading(false)
    }
  }, [documentId])

  useEffect(() => {
    load()
  }, [load])

  async function handleRename() {
    if (!draftTitle.trim()) return
    try {
      const updated = await renameDocument(documentId, draftTitle.trim())
      setDocument((current) => ({ ...current, title: updated.title }))
      setIsRenaming(false)
    } catch (caught) {
      setActionError(friendlyError(caught))
    }
  }

  async function handleDelete() {
    // Deleting removes the extracted text permanently, so confirm first.
    if (
      !window.confirm(
        'Delete this document? Conversations that already used it keep their history.',
      )
    ) {
      return
    }
    setIsDeleting(true)
    try {
      await deleteDocument(documentId)
      navigate('/documents', { replace: true })
    } catch (caught) {
      setActionError(friendlyError(caught))
      setIsDeleting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-3 py-16 text-slate-500">
        <Spinner />
        <span className="text-sm">Loading document…</span>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <Alert variant="error">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/documents')}>
          Back to documents
        </Button>
      </div>
    )
  }

  const metadata = Object.entries(document.metadata ?? {})

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {isRenaming ? (
            <div className="flex flex-wrap items-end gap-2">
              <TextInput
                label="Document name"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
              />
              <Button onClick={handleRename}>Save</Button>
              <Button variant="ghost" onClick={() => setIsRenaming(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <>
              <h1 className="truncate text-xl font-semibold text-slate-900">
                {document.title}
              </h1>
              {/* The original upload name, which a rename never changes. */}
              {document.title !== document.filename && (
                <p className="mt-1 truncate text-xs text-slate-400">
                  Uploaded as {document.filename}
                </p>
              )}
            </>
          )}
        </div>

        {!isRenaming && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button
              onClick={() =>
                navigate('/conversations', {
                  state: {
                    documentId: document.id,
                    documentTitle: document.title,
                  },
                })
              }
            >
              Use in a conversation
            </Button>
            <Button variant="secondary" onClick={() => setIsRenaming(true)}>
              Rename
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={isDeleting}>
              Delete
            </Button>
          </div>
        )}
      </header>

      {actionError && <Alert variant="error">{actionError}</Alert>}

      <Card title="Details">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <dt className="text-xs text-slate-500">Type</dt>
            <dd className="text-sm font-medium text-slate-800">{document.extension}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Size</dt>
            <dd className="text-sm font-medium text-slate-800">
              {formatBytes(document.size_bytes)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Characters</dt>
            <dd className="text-sm font-medium text-slate-800">
              {document.characters.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Uploaded</dt>
            <dd className="text-sm font-medium text-slate-800">
              {formatDate(document.created_at)}
            </dd>
          </div>
        </dl>

        {metadata.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {metadata.map(([key, value]) => (
              <Badge key={key} tone="indigo">
                {humanise(key)}: {String(value)}
              </Badge>
            ))}
          </div>
        )}
      </Card>

      <Card title="Extracted text" actions={<CopyButton text={document.text} />}>
        {/* Rendered as escaped plain text — never as HTML or markdown, so an
            uploaded document cannot inject markup into the page. */}
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <ProseBlock text={document.text} />
        </div>
      </Card>
    </div>
  )
}
