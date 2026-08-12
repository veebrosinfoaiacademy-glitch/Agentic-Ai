import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import * as conversationsApi from '../api/conversations'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Select,
  Spinner,
  TextInput,
} from '../components/common'
import { friendlyError, humanise } from '../utils/errorMessages'

const AGENT_OPTIONS = [
  { value: 'content', label: 'Content Agent' },
  { value: 'developer', label: 'Developer Agent' },
]

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export default function Conversations() {
  const navigate = useNavigate()

  const [conversations, setConversations] = useState([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  const [title, setTitle] = useState('')
  const [agentType, setAgentType] = useState('content')
  const [fieldError, setFieldError] = useState(null)
  const [isCreating, setIsCreating] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await conversationsApi.listConversations({ pageSize: 50 })
      setConversations(data.conversations)
      setTotal(data.total)
    } catch (caught) {
      setError(friendlyError(caught))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate(event) {
    event.preventDefault()
    if (isCreating) return

    setFieldError(null)
    setError(null)
    if (!title.trim()) {
      setFieldError('Give the conversation a name')
      return
    }

    setIsCreating(true)
    try {
      const created = await conversationsApi.createConversation(title.trim(), agentType)
      navigate(`/conversations/${created.id}`)
    } catch (caught) {
      setFieldError(caught.fieldErrors?.title ?? null)
      setError(friendlyError(caught))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Conversations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Your saved agent sessions. Only you can see these.
        </p>
      </header>

      <Card title="Start a conversation">
        <form onSubmit={handleCreate} noValidate className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label="Name"
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              error={fieldError}
              placeholder="Python code review"
            />
            <Select
              label="Agent"
              hint="Fixed once created"
              value={agentType}
              onChange={(event) => setAgentType(event.target.value)}
              options={AGENT_OPTIONS}
            />
          </div>
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" loading={isCreating}>
            {isCreating ? 'Creating…' : 'Create conversation'}
          </Button>
        </form>
      </Card>

      <Card title={total ? `Your conversations (${total})` : 'Your conversations'}>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 py-10 text-slate-500">
            <Spinner />
            <span className="text-sm">Loading conversations…</span>
          </div>
        ) : conversations.length === 0 ? (
          <EmptyState
            title="No conversations yet"
            description="Create one above to start a saved session with an agent."
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <Link
                  to={`/conversations/${conversation.id}`}
                  className="flex items-center justify-between gap-4 py-3 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
                >
                  <div className="min-w-0">
                    {/* Titles, not database ids — the id lives in the URL only. */}
                    <p className="truncate text-sm font-medium text-slate-800">
                      {conversation.title}
                    </p>
                    <p className="text-xs text-slate-500">
                      Updated {formatDate(conversation.updated_at)}
                    </p>
                  </div>
                  <Badge tone={conversation.agent_type === 'content' ? 'indigo' : 'sky'}>
                    {humanise(conversation.agent_type)}
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
