import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authApi from '../api/auth'
import * as conversationsApi from '../api/conversations'
import * as documentsApi from '../api/documents'
import * as usageApi from '../api/usage'
import { FAKE_USER, TOKEN_KEY, apiError, renderApp } from './utils'

vi.mock('../api/auth')
vi.mock('../api/documents')
vi.mock('../api/usage')
vi.mock('../api/conversations', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    createConversation: vi.fn(),
    listConversations: vi.fn(),
    getConversation: vi.fn(),
    renameConversation: vi.fn(),
    deleteConversation: vi.fn(),
    sendMessage: vi.fn(),
  }
})

const DOCUMENT = {
  id: '507f1f77bcf86cd799439011',
  title: 'Annual report',
  filename: 'annual_report.pdf',
  extension: '.pdf',
  content_type: 'application/pdf',
  size_bytes: 20480,
  characters: 1234,
  metadata: { page_count: 12, pages_with_text: 12 },
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
}

const DETAIL = { ...DOCUMENT, text: 'Revenue rose 18 percent this year.' }

beforeEach(() => {
  localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
  authApi.getCurrentUser.mockResolvedValue(FAKE_USER)
  usageApi.getUsage.mockResolvedValue({
    hour: { used: 0, limit: 100, remaining: 100, resets_at: '2030-01-01T00:00:00Z' },
    day: { used: 0, limit: 500, remaining: 500, resets_at: '2030-01-01T00:00:00Z' },
    limited: true,
  })
  documentsApi.getSupportedTypes.mockResolvedValue({
    extensions: ['.txt', '.md', '.csv', '.pdf', '.docx'],
    max_file_size_mb: 10,
    max_extracted_characters: 100000,
    ocr_supported: false,
  })
  documentsApi.listDocuments.mockResolvedValue({
    documents: [], page: 1, page_size: 50, total: 0, has_more: false,
  })
  conversationsApi.listConversations.mockResolvedValue({
    conversations: [], page: 1, page_size: 50, total: 0, has_more: false,
  })
})

describe('Documents list', () => {
  it('shows an empty state when there are none', async () => {
    renderApp('/documents')

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument()
  })

  it('lists stored documents with size and character counts', async () => {
    documentsApi.listDocuments.mockResolvedValue({
      documents: [DOCUMENT], page: 1, page_size: 50, total: 1, has_more: false,
    })

    renderApp('/documents')

    expect(await screen.findByText('Annual report')).toBeInTheDocument()
    expect(screen.getByText(/20\.0 KB · 1,234 characters/)).toBeInTheDocument()
    // The database id belongs in the URL, not on screen.
    expect(screen.queryByText(DOCUMENT.id)).toBeNull()
  })

  it('shows the server-supplied formats and limits', async () => {
    renderApp('/documents')

    expect(
      await screen.findByText(/\.txt, \.md, \.csv, \.pdf, \.docx/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/up to 10 MB/i)).toBeInTheDocument()
    expect(documentsApi.getSupportedTypes).toHaveBeenCalled()
  })

  it('uploads a file and opens its detail page', async () => {
    const user = userEvent.setup()
    documentsApi.uploadDocument.mockResolvedValue(DETAIL)
    documentsApi.getDocument.mockResolvedValue(DETAIL)

    renderApp('/documents')
    await screen.findByText(/\.txt, \.md/i)

    const input = screen.getByLabelText(/choose a file/i)
    await user.upload(input, new File(['%PDF'], 'annual_report.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: /upload and extract/i }))

    expect(
      await screen.findByRole('heading', { name: 'Annual report' }),
    ).toBeInTheDocument()
  })

  it('rejects an unsupported extension before uploading', async () => {
    // applyAccept: false bypasses the input's accept filter so the handler's
    // own check is exercised — it still matters for drag-and-drop.
    const user = userEvent.setup({ applyAccept: false })
    renderApp('/documents')
    await screen.findByText(/\.txt, \.md/i)

    await user.upload(
      screen.getByLabelText(/choose a file/i),
      new File(['print(1)'], 'script.py', { type: 'text/x-python' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/not supported/i)
    expect(documentsApi.uploadDocument).not.toHaveBeenCalled()
  })

  it('maps a backend upload failure to a readable message', async () => {
    const user = userEvent.setup()
    documentsApi.uploadDocument.mockRejectedValue(
      apiError('DOCUMENT_TEXT_NOT_FOUND', 'No readable text was found.', {
        status: 422,
      }),
    )

    renderApp('/documents')
    await screen.findByText(/\.txt, \.md/i)
    await user.upload(
      screen.getByLabelText(/choose a file/i),
      new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }),
    )
    await user.click(screen.getByRole('button', { name: /upload and extract/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/no readable text/i)
  })
})

describe('Document detail', () => {
  beforeEach(() => {
    documentsApi.getDocument.mockResolvedValue(DETAIL)
  })

  it('shows metadata and the extracted text', async () => {
    renderApp(`/documents/${DOCUMENT.id}`)

    expect(
      await screen.findByRole('heading', { name: 'Annual report' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Revenue rose 18 percent this year.')).toBeInTheDocument()
    expect(screen.getByText(/page count: 12/i)).toBeInTheDocument()
    expect(screen.getByText('20.0 KB')).toBeInTheDocument()
  })

  it('renders document text as escaped plain text, never as markup', async () => {
    documentsApi.getDocument.mockResolvedValue({
      ...DETAIL,
      text: '<img src=x onerror="alert(1)"> **not bold**',
    })

    renderApp(`/documents/${DOCUMENT.id}`)

    // The tags appear as literal characters; no element was created from them.
    expect(
      await screen.findByText(/<img src=x onerror="alert\(1\)"> \*\*not bold\*\*/),
    ).toBeInTheDocument()
    expect(window.document.querySelector('img')).toBeNull()
  })

  it('shows the original filename when the title has been changed', async () => {
    renderApp(`/documents/${DOCUMENT.id}`)

    expect(await screen.findByText(/uploaded as annual_report\.pdf/i)).toBeInTheDocument()
  })

  it('renames a document', async () => {
    const user = userEvent.setup()
    documentsApi.renameDocument.mockResolvedValue({ ...DOCUMENT, title: 'Q4 report' })

    renderApp(`/documents/${DOCUMENT.id}`)
    await user.click(await screen.findByRole('button', { name: /rename/i }))
    const input = screen.getByLabelText(/document name/i)
    await user.clear(input)
    await user.type(input, 'Q4 report')
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(await screen.findByRole('heading', { name: 'Q4 report' })).toBeInTheDocument()
    expect(documentsApi.renameDocument).toHaveBeenCalledWith(DOCUMENT.id, 'Q4 report')
  })

  it('confirms before deleting, then returns to the list', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    documentsApi.deleteDocument.mockResolvedValue(null)

    renderApp(`/documents/${DOCUMENT.id}`)
    await user.click(await screen.findByRole('button', { name: /delete/i }))

    expect(window.confirm).toHaveBeenCalled()
    expect(documentsApi.deleteDocument).toHaveBeenCalledWith(DOCUMENT.id)
    expect(await screen.findByRole('heading', { name: /^documents$/i })).toBeInTheDocument()
  })

  it('does not delete when the confirmation is dismissed', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderApp(`/documents/${DOCUMENT.id}`)
    await user.click(await screen.findByRole('button', { name: /delete/i }))

    expect(documentsApi.deleteDocument).not.toHaveBeenCalled()
  })

  it('shows a safe message when the document is not accessible', async () => {
    // What another user's document looks like: identical to a missing one.
    documentsApi.getDocument.mockRejectedValue(
      apiError('DOCUMENT_NOT_FOUND', 'Document not found', { status: 404 }),
    )

    renderApp(`/documents/${DOCUMENT.id}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(/not found/i)
    expect(screen.getByRole('button', { name: /back to documents/i })).toBeInTheDocument()
  })
})

describe('using a document in a conversation', () => {
  const CONVERSATION = {
    id: '507f1f77bcf86cd799439099',
    title: 'Report review',
    agent_type: 'content',
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-01-01T10:00:00Z',
    message_count: 0,
    messages: [],
  }

  beforeEach(() => {
    documentsApi.getDocument.mockResolvedValue(DETAIL)
    conversationsApi.getConversation.mockResolvedValue(CONVERSATION)
  })

  it('carries the document through to the conversation list', async () => {
    const user = userEvent.setup()
    conversationsApi.listConversations.mockResolvedValue({
      conversations: [CONVERSATION], page: 1, page_size: 50, total: 1, has_more: false,
    })

    renderApp(`/documents/${DOCUMENT.id}`)
    await user.click(await screen.findByRole('button', { name: /use in a conversation/i }))

    expect(await screen.findByText(/document attached/i)).toBeInTheDocument()
    expect(screen.getByText('Annual report')).toBeInTheDocument()
  })

  it('sends document_id rather than the document text', async () => {
    const user = userEvent.setup()
    conversationsApi.listConversations.mockResolvedValue({
      conversations: [CONVERSATION], page: 1, page_size: 50, total: 1, has_more: false,
    })
    conversationsApi.sendMessage.mockResolvedValue({
      conversation_id: CONVERSATION.id,
      user_message: {
        id: 'm1', role: 'user', content: 'summarize "Annual report"',
        task_type: 'summarize', model: null, created_at: '2026-01-02T10:00:00Z',
        data: null,
        source: { type: 'document', document_id: DOCUMENT.id, filename: 'annual_report.pdf' },
      },
      assistant_message: {
        id: 'm2', role: 'assistant', content: 'Revenue rose 18 percent.',
        task_type: 'summarize', model: 'llama-3.3-70b-versatile',
        created_at: '2026-01-02T10:00:02Z', data: null,
        source: { type: 'document', document_id: DOCUMENT.id, filename: 'annual_report.pdf' },
      },
    })

    renderApp(`/documents/${DOCUMENT.id}`)
    await user.click(await screen.findByRole('button', { name: /use in a conversation/i }))
    await user.click(await screen.findByText('Report review'))

    expect(await screen.findByText(/using/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    const [, payload] = conversationsApi.sendMessage.mock.calls[0]
    expect(payload.documentId).toBe(DOCUMENT.id)
    // The client never sends the document's contents.
    expect(JSON.stringify(payload)).not.toContain('Revenue rose 18 percent this year.')
  })

  it('shows the source on messages that came from a document', async () => {
    conversationsApi.getConversation.mockResolvedValue({
      ...CONVERSATION,
      message_count: 2,
      messages: [
        {
          id: 'm1', role: 'user', content: 'summarize "Annual report"',
          task_type: 'summarize', model: null, created_at: '2026-01-02T10:00:00Z',
          data: null,
          source: { type: 'document', document_id: DOCUMENT.id, filename: 'annual_report.pdf' },
        },
        {
          id: 'm2', role: 'assistant', content: 'Revenue rose 18 percent.',
          task_type: 'summarize', model: 'llama-3.3-70b-versatile',
          created_at: '2026-01-02T10:00:02Z', data: null, source: null,
        },
      ],
    })

    renderApp(`/conversations/${CONVERSATION.id}`)

    const transcript = await screen.findByRole('list')
    const items = within(transcript).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent(/source: annual_report\.pdf/i)
    expect(items[1]).not.toHaveTextContent(/source:/i)
  })

  it('omits the source line for a typed message', async () => {
    conversationsApi.getConversation.mockResolvedValue({
      ...CONVERSATION,
      message_count: 1,
      messages: [
        {
          id: 'm1', role: 'user', content: 'Some typed text.',
          task_type: 'summarize', model: null, created_at: '2026-01-02T10:00:00Z',
          data: null, source: null,
        },
      ],
    })

    renderApp(`/conversations/${CONVERSATION.id}`)

    expect(await screen.findByText('Some typed text.')).toBeInTheDocument()
    expect(screen.queryByText(/source:/i)).toBeNull()
  })

  it('still requires text when no document is attached', async () => {
    const user = userEvent.setup()

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.click(await screen.findByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/enter something to send/i)).toBeInTheDocument()
    expect(conversationsApi.sendMessage).not.toHaveBeenCalled()
  })
})
