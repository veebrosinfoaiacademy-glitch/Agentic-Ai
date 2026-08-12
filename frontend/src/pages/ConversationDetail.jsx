import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import * as conversationsApi from '../api/conversations'
import {
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ProseBlock,
  Select,
  Spinner,
  TextArea,
  TextInput,
} from '../components/common'
import { friendlyError, humanise } from '../utils/errorMessages'

/** Placeholder text per task, so the input explains what it expects. */
const PROMPT_HINTS = {
  generate: 'Describe what to create…',
  summarize: 'Paste the text to summarise…',
  rewrite: 'Paste the text to rewrite…',
  tone: 'Paste the text whose tone should change…',
  audience: 'Paste the text to re-pitch…',
  format: 'Paste the text to reformat…',
  extract: 'Paste the text to extract information from…',
  explain: 'Paste the code to explain…',
  review: 'Paste the code to review…',
  refactor: 'Paste the code to refactor…',
  tests: 'Paste the code to write tests for…',
  debug: 'Paste the code that is misbehaving…',
  document: 'Paste the code to document…',
}

const CODE_TASKS = new Set([
  'explain', 'review', 'refactor', 'tests', 'debug', 'document',
])

function formatTime(value) {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export default function ConversationDetail() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const transcriptEnd = useRef(null)

  const [conversation, setConversation] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  const [taskType, setTaskType] = useState('')
  const [prompt, setPrompt] = useState('')
  const [sendError, setSendError] = useState(null)
  const [fieldError, setFieldError] = useState(null)
  const [isSending, setIsSending] = useState(false)

  const [isRenaming, setIsRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const data = await conversationsApi.getConversation(conversationId)
      setConversation(data)
      setDraftTitle(data.title)
      setTaskType((current) => current || conversationsApi.TASKS_BY_AGENT[data.agent_type][0])
    } catch (caught) {
      setLoadError(friendlyError(caught))
    } finally {
      setIsLoading(false)
    }
  }, [conversationId])

  useEffect(() => {
    load()
  }, [load])

  // Keep the newest turn in view as the transcript grows.
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: 'nearest' })
  }, [conversation?.messages?.length])

  async function handleSend(event) {
    event.preventDefault()
    if (isSending) return

    setSendError(null)
    setFieldError(null)
    if (!prompt.trim()) {
      setFieldError('Enter something to send')
      return
    }

    setIsSending(true)
    try {
      const result = await conversationsApi.sendMessage(conversationId, {
        taskType,
        prompt: prompt.trim(),
      })
      setConversation((current) => ({
        ...current,
        messages: [...current.messages, result.user_message, result.assistant_message],
      }))
      setPrompt('')
    } catch (caught) {
      // The backend keeps the user's message on a provider failure, so a
      // reload will show it. Refresh rather than guess at local state.
      setSendError(friendlyError(caught))
      load()
    } finally {
      setIsSending(false)
    }
  }

  async function handleRename() {
    if (!draftTitle.trim()) return
    try {
      const updated = await conversationsApi.renameConversation(
        conversationId,
        draftTitle.trim(),
      )
      setConversation((current) => ({ ...current, title: updated.title }))
      setIsRenaming(false)
    } catch (caught) {
      setSendError(friendlyError(caught))
    }
  }

  async function handleDelete() {
    // Deleting removes the transcript too, so confirm first.
    if (!window.confirm('Delete this conversation and all of its messages?')) return
    setIsDeleting(true)
    try {
      await conversationsApi.deleteConversation(conversationId)
      navigate('/conversations', { replace: true })
    } catch (caught) {
      setSendError(friendlyError(caught))
      setIsDeleting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-3 py-16 text-slate-500">
        <Spinner />
        <span className="text-sm">Loading conversation…</span>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <Alert variant="error">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/conversations')}>
          Back to conversations
        </Button>
      </div>
    )
  }

  const tasks = conversationsApi.TASKS_BY_AGENT[conversation.agent_type] ?? []

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {isRenaming ? (
            <div className="flex flex-wrap items-end gap-2">
              <TextInput
                label="Conversation name"
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
                {conversation.title}
              </h1>
              <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">
                <Badge tone={conversation.agent_type === 'content' ? 'indigo' : 'sky'}>
                  {humanise(conversation.agent_type)}
                </Badge>
                <span>{conversation.messages.length} messages</span>
              </p>
            </>
          )}
        </div>

        {!isRenaming && (
          <div className="flex shrink-0 gap-2">
            <Button variant="secondary" onClick={() => setIsRenaming(true)}>
              Rename
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={isDeleting}>
              Delete
            </Button>
          </div>
        )}
      </header>

      <Card title="Transcript">
        {conversation.messages.length === 0 ? (
          <EmptyState
            title="No messages yet"
            description="Send the first message below to start this conversation."
          />
        ) : (
          <ol className="space-y-4">
            {conversation.messages.map((message) => (
              <li key={message.id}>
                <Message message={message} />
              </li>
            ))}
            <li ref={transcriptEnd} aria-hidden="true" />
          </ol>
        )}
      </Card>

      <Card title="Send a message">
        <form onSubmit={handleSend} noValidate className="space-y-4">
          <Select
            label="Task"
            value={taskType}
            onChange={(event) => setTaskType(event.target.value)}
            options={tasks.map((task) => ({ value: task, label: humanise(task) }))}
          />
          <TextArea
            label="Your message"
            required
            rows={CODE_TASKS.has(taskType) ? 12 : 8}
            mono={CODE_TASKS.has(taskType)}
            spellCheck={!CODE_TASKS.has(taskType)}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            error={fieldError}
            placeholder={PROMPT_HINTS[taskType] ?? 'Type your message…'}
          />
          {sendError && <Alert variant="error">{sendError}</Alert>}
          <Button type="submit" loading={isSending}>
            {isSending ? 'Waiting for the agent…' : 'Send'}
          </Button>
        </form>
      </Card>
    </div>
  )
}

function Message({ message }) {
  const isUser = message.role === 'user'

  return (
    <article
      className={`rounded-lg border p-4 ${
        isUser ? 'border-slate-200 bg-slate-50' : 'border-indigo-100 bg-white'
      }`}
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        {/* Text, not just colour, distinguishes the two speakers. */}
        <Badge tone={isUser ? 'slate' : 'indigo'}>{isUser ? 'You' : 'Agent'}</Badge>
        {message.task_type && <Badge>{humanise(message.task_type)}</Badge>}
        <span className="text-xs text-slate-400">{formatTime(message.created_at)}</span>
        {!isUser && <span className="ml-auto"><CopyButton text={message.content} /></span>}
      </header>

      <ProseBlock text={message.content} />

      {message.model && (
        <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-400">
          {message.model}
        </p>
      )}
    </article>
  )
}
