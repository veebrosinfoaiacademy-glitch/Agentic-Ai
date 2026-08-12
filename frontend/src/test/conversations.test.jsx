import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authApi from '../api/auth'
import * as conversationsApi from '../api/conversations'
import * as documentsApi from '../api/documents'
import { FAKE_USER, TOKEN_KEY, apiError, renderApp } from './utils'

vi.mock('../api/auth')
vi.mock('../api/conversations', async (importOriginal) => {
  // TASKS_BY_AGENT is real data the pages read; only the calls are mocked.
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
vi.mock('../api/documents')

const CONVERSATION = {
  id: '507f1f77bcf86cd799439011',
  title: 'Python Code Review',
  agent_type: 'developer',
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-02T10:00:00Z',
  message_count: 2,
}

const TRANSCRIPT = {
  ...CONVERSATION,
  messages: [
    {
      id: 'm1',
      role: 'user',
      content: 'def add(a, b): return a + b',
      task_type: 'explain',
      model: null,
      created_at: '2026-01-01T10:00:00Z',
      data: null,
    },
    {
      id: 'm2',
      role: 'assistant',
      content: 'It adds two numbers together.',
      task_type: 'explain',
      model: 'llama-3.3-70b-versatile',
      created_at: '2026-01-01T10:00:05Z',
      data: { summary: 'It adds two numbers together.' },
    },
  ],
}

beforeEach(() => {
  localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
  authApi.getCurrentUser.mockResolvedValue(FAKE_USER)
  documentsApi.getSupportedTypes.mockResolvedValue({
    extensions: ['.txt'], max_file_size_mb: 10, max_extracted_characters: 100000,
    ocr_supported: false,
  })
  conversationsApi.listConversations.mockResolvedValue({
    conversations: [], page: 1, page_size: 20, total: 0, has_more: false,
  })
})

describe('Conversations list', () => {
  it('shows an empty state when there are none', async () => {
    renderApp('/conversations')

    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument()
  })

  it('lists conversations by title, not by database id', async () => {
    conversationsApi.listConversations.mockResolvedValue({
      conversations: [CONVERSATION], page: 1, page_size: 20, total: 1, has_more: false,
    })

    renderApp('/conversations')

    expect(await screen.findByText('Python Code Review')).toBeInTheDocument()
    // The id belongs in the URL, not on screen.
    expect(screen.queryByText(CONVERSATION.id)).toBeNull()
  })

  it('creates a conversation and opens it', async () => {
    const user = userEvent.setup()
    conversationsApi.createConversation.mockResolvedValue(CONVERSATION)
    conversationsApi.getConversation.mockResolvedValue(TRANSCRIPT)

    renderApp('/conversations')

    await user.type(await screen.findByLabelText(/^name/i), 'Python Code Review')
    await user.selectOptions(screen.getByLabelText(/agent/i), 'developer')
    await user.click(screen.getByRole('button', { name: /create conversation/i }))

    expect(conversationsApi.createConversation).toHaveBeenCalledWith(
      'Python Code Review',
      'developer',
    )
    expect(
      await screen.findByRole('heading', { name: 'Python Code Review' }),
    ).toBeInTheDocument()
  })

  it('validates an empty name before calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/conversations')

    await user.click(await screen.findByRole('button', { name: /create conversation/i }))

    expect(await screen.findByText(/give the conversation a name/i)).toBeInTheDocument()
    expect(conversationsApi.createConversation).not.toHaveBeenCalled()
  })

  it('shows a readable message when listing fails', async () => {
    conversationsApi.listConversations.mockRejectedValue(
      apiError('DATABASE_UNAVAILABLE', 'temporarily unavailable', { status: 503 }),
    )

    renderApp('/conversations')

    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument()
  })
})

describe('Conversation detail', () => {
  beforeEach(() => {
    conversationsApi.getConversation.mockResolvedValue(TRANSCRIPT)
  })

  it('renders the transcript in order with speakers labelled', async () => {
    renderApp(`/conversations/${CONVERSATION.id}`)

    const transcript = await screen.findByRole('list')
    const items = within(transcript).getAllByRole('listitem')

    expect(items[0]).toHaveTextContent('You')
    expect(items[0]).toHaveTextContent('def add(a, b): return a + b')
    expect(items[1]).toHaveTextContent('Agent')
    expect(items[1]).toHaveTextContent('It adds two numbers together.')
  })

  it('offers only the tasks this conversation’s agent supports', async () => {
    renderApp(`/conversations/${CONVERSATION.id}`)

    const select = await screen.findByLabelText(/^task/i)
    const values = within(select).getAllByRole('option').map((o) => o.value)

    expect(values).toEqual([
      'generate', 'explain', 'review', 'refactor', 'tests', 'debug', 'document',
    ])
    // Content-only tasks must not appear in a developer conversation.
    expect(values).not.toContain('summarize')
    expect(values).not.toContain('tone')
  })

  it('sends a message and appends both turns', async () => {
    const user = userEvent.setup()
    conversationsApi.sendMessage.mockResolvedValue({
      conversation_id: CONVERSATION.id,
      user_message: {
        id: 'm3', role: 'user', content: 'x = 1', task_type: 'explain',
        model: null, created_at: '2026-01-03T10:00:00Z', data: null,
      },
      assistant_message: {
        id: 'm4', role: 'assistant', content: 'Assigns 1 to x.', task_type: 'explain',
        model: 'llama-3.3-70b-versatile', created_at: '2026-01-03T10:00:02Z', data: null,
      },
    })

    renderApp(`/conversations/${CONVERSATION.id}`)

    // The task defaults to the agent's first; pick one explicitly, as a user would.
    await user.selectOptions(await screen.findByLabelText(/^task/i), 'explain')
    await user.type(screen.getByLabelText(/your message/i), 'x = 1')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText('Assigns 1 to x.')).toBeInTheDocument()
    expect(conversationsApi.sendMessage).toHaveBeenCalledWith(CONVERSATION.id, {
      taskType: 'explain',
      prompt: 'x = 1',
    })
  })

  it('disables the send button while waiting for the agent', async () => {
    const user = userEvent.setup()
    conversationsApi.sendMessage.mockReturnValue(new Promise(() => {}))

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.type(await screen.findByLabelText(/your message/i), 'x = 1')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(screen.getByRole('button', { name: /waiting for the agent/i })).toBeDisabled()
    expect(conversationsApi.sendMessage).toHaveBeenCalledTimes(1)
  })

  it('surfaces a provider failure without inventing a reply', async () => {
    const user = userEvent.setup()
    conversationsApi.sendMessage.mockRejectedValue(
      apiError('AI_PROVIDER_ERROR', 'temporarily unavailable', { status: 502 }),
    )

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.type(await screen.findByLabelText(/your message/i), 'x = 1')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/temporarily unavailable/i)
    // No fabricated assistant turn was added.
    expect(screen.queryByText(/assigns 1 to x/i)).toBeNull()
  })

  it('rejects a task the agent cannot perform, using the backend message', async () => {
    const user = userEvent.setup()
    conversationsApi.sendMessage.mockRejectedValue(
      apiError(
        'TASK_NOT_SUPPORTED',
        "'summarize' is not a developer task.",
        { status: 422 },
      ),
    )

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.type(await screen.findByLabelText(/your message/i), 'text')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/not a developer task/i)
  })

  it('renames a conversation', async () => {
    const user = userEvent.setup()
    conversationsApi.renameConversation.mockResolvedValue({
      ...CONVERSATION,
      title: 'Renamed session',
    })

    renderApp(`/conversations/${CONVERSATION.id}`)

    await user.click(await screen.findByRole('button', { name: /rename/i }))
    const input = screen.getByLabelText(/conversation name/i)
    await user.clear(input)
    await user.type(input, 'Renamed session')
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(
      await screen.findByRole('heading', { name: 'Renamed session' }),
    ).toBeInTheDocument()
  })

  it('confirms before deleting, then returns to the list', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    conversationsApi.deleteConversation.mockResolvedValue(null)

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.click(await screen.findByRole('button', { name: /delete/i }))

    expect(window.confirm).toHaveBeenCalled()
    expect(conversationsApi.deleteConversation).toHaveBeenCalledWith(CONVERSATION.id)
    expect(await screen.findByRole('heading', { name: /^conversations$/i })).toBeInTheDocument()
  })

  it('does not delete when the confirmation is dismissed', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderApp(`/conversations/${CONVERSATION.id}`)
    await user.click(await screen.findByRole('button', { name: /delete/i }))

    expect(conversationsApi.deleteConversation).not.toHaveBeenCalled()
  })

  it('shows a safe message when the conversation is not accessible', async () => {
    // What another user's conversation looks like: identical to a missing one.
    conversationsApi.getConversation.mockRejectedValue(
      apiError('CONVERSATION_NOT_FOUND', 'Conversation not found', { status: 404 }),
    )

    renderApp(`/conversations/${CONVERSATION.id}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(/not found/i)
    expect(
      screen.getByRole('button', { name: /back to conversations/i }),
    ).toBeInTheDocument()
  })
})

describe('Dashboard recent conversations', () => {
  it('lists real conversations from the API', async () => {
    conversationsApi.listConversations.mockResolvedValue({
      conversations: [CONVERSATION], page: 1, page_size: 5, total: 1, has_more: false,
    })

    renderApp('/dashboard')

    expect(await screen.findByText('Python Code Review')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view all/i })).toBeInTheDocument()
  })

  it('shows an empty state rather than inventing activity', async () => {
    renderApp('/dashboard')

    expect(await screen.findByText(/saved agent sessions will appear here/i)).toBeInTheDocument()
    expect(screen.queryByText(/saved hours|productivity score/i)).toBeNull()
  })
})

describe('protected routes', () => {
  it.each(['/conversations', '/conversations/507f1f77bcf86cd799439011'])(
    'redirects %s to login when signed out',
    async (route) => {
      localStorage.clear()

      renderApp(route)

      expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    },
  )
})
