import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listConversations } from '../api/conversations'
import { Badge, Card, EmptyState, Spinner } from '../components/common'
import { useAuth } from '../context/useAuth'
import { humanise } from '../utils/errorMessages'

/**
 * Deliberately free of statistics.
 *
 * There is no backend endpoint for usage counts, saved hours or accuracy, so
 * showing any would mean inventing them. Real numbers can appear here once
 * conversation history exists.
 */
const AGENTS = [
  {
    to: '/content',
    name: 'Content Agent',
    description: 'Generate, rewrite, summarize and transform content.',
    action: 'Open Content Agent',
    tasks: ['Generate', 'Summarize', 'Rewrite', 'Tone', 'Audience', 'Format', 'Extract'],
    icon: '✎',
  },
  {
    to: '/developer',
    name: 'Developer Agent',
    description: 'Generate, explain, review, refactor and debug code.',
    action: 'Open Developer Agent',
    tasks: ['Generate', 'Explain', 'Review', 'Refactor', 'Tests', 'Debug', 'Document'],
    icon: '⌘',
  },
  {
    to: '/documents',
    name: 'Documents',
    description: 'Upload and extract text from documents.',
    action: 'Manage Documents',
    tasks: ['TXT', 'MD', 'CSV', 'PDF', 'DOCX'],
    icon: '⬒',
  },
]

/** Real data from the API — still no invented metrics. */
function RecentConversations() {
  const [conversations, setConversations] = useState([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    listConversations({ pageSize: 5 })
      .then((data) => {
        if (!cancelled) setConversations(data.conversations)
      })
      .catch(() => {
        // Non-fatal: the dashboard's agent cards still work.
        if (!cancelled) setConversations([])
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Card
      title="Recent conversations"
      actions={
        <Link
          to="/conversations"
          className="text-sm font-medium text-indigo-600 underline-offset-2 hover:underline"
        >
          View all
        </Link>
      }
    >
      {isLoading ? (
        <div className="flex items-center justify-center gap-3 py-6 text-slate-500">
          <Spinner />
          <span className="text-sm">Loading…</span>
        </div>
      ) : conversations.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          description="Saved agent sessions will appear here."
        />
      ) : (
        <ul className="divide-y divide-slate-100">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <Link
                to={`/conversations/${conversation.id}`}
                className="flex items-center justify-between gap-4 py-2.5 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
              >
                <span className="truncate text-sm text-slate-800">
                  {conversation.title}
                </span>
                <Badge tone={conversation.agent_type === 'content' ? 'indigo' : 'sky'}>
                  {humanise(conversation.agent_type)}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function Dashboard() {
  const { user } = useAuth()

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Welcome back</h1>
        <p className="mt-1 truncate text-sm text-slate-500" title={user?.email}>
          Signed in as {user?.email}
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {AGENTS.map(({ to, name, description, action, tasks, icon }) => (
          <div
            key={to}
            className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <span
              aria-hidden="true"
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500"
            >
              {icon}
            </span>

            <h2 className="mt-4 text-base font-semibold text-slate-900">{name}</h2>
            <p className="mt-1 text-sm text-slate-600">{description}</p>

            <ul className="mt-3 flex flex-wrap gap-1.5">
              {tasks.map((task) => (
                <li
                  key={task}
                  className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-500"
                >
                  {task}
                </li>
              ))}
            </ul>

            <Link
              to={to}
              className="mt-5 inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
            >
              {action}
            </Link>
          </div>
        ))}
      </div>

      <RecentConversations />

      <p className="text-xs text-slate-400">
        Requests are sent to your own backend, which calls the AI provider. No
        provider credentials exist in this browser.
      </p>
    </div>
  )
}
