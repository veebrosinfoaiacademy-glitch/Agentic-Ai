import { useEffect, useState } from 'react'

import { getUsage } from '../../api/usage'
import { Card, EmptyState, Spinner } from './index'

/**
 * Shows the signed-in user's AI usage against their limits.
 *
 * Real server data only — no estimates, no client-side counting. If usage
 * cannot be read, it says so rather than showing a reassuring zero.
 */

function formatReset(isoString) {
  if (!isoString) return ''
  const resets = new Date(isoString)
  const minutes = Math.round((resets - Date.now()) / 60000)
  if (minutes <= 0) return 'resetting now'
  if (minutes < 60) return `resets in ${minutes} min`
  const hours = Math.round(minutes / 60)
  return `resets in ${hours} hour${hours === 1 ? '' : 's'}`
}

function Bar({ label, window }) {
  const { used, limit, remaining, resets_at: resetsAt } = window
  const unlimited = !limit
  const percent = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100))

  // Colour alone never carries the meaning; the text below states it too.
  const tone =
    percent >= 100 ? 'bg-red-500' : percent >= 80 ? 'bg-amber-500' : 'bg-indigo-500'

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-sm text-slate-600">
          {unlimited ? 'Unlimited' : `${used} / ${limit}`}
        </span>
      </div>

      {!unlimited && (
        <div
          className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-200"
          role="progressbar"
          aria-valuenow={used}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-label={`${label}: ${used} of ${limit} requests used`}
        >
          <div className={`h-full ${tone}`} style={{ width: `${percent}%` }} />
        </div>
      )}

      <p className="mt-1 text-xs text-slate-500">
        {unlimited
          ? 'No limit configured'
          : `${remaining} remaining · ${formatReset(resetsAt)}`}
      </p>
    </div>
  )
}

export default function UsageMeter() {
  const [usage, setUsage] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    getUsage()
      .then((data) => {
        if (!cancelled) setUsage(data)
      })
      .catch(() => {
        // Non-fatal — the rest of the dashboard still works.
        if (!cancelled) setFailed(true)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Card title="AI usage">
      {isLoading ? (
        <div className="flex items-center justify-center gap-3 py-6 text-slate-500">
          <Spinner />
          <span className="text-sm">Loading usage…</span>
        </div>
      ) : failed || !usage ? (
        <EmptyState
          title="Usage unavailable"
          description="Your current usage could not be loaded. Requests are unaffected."
        />
      ) : (
        <div className="space-y-4">
          <Bar label="This hour" window={usage.hour} />
          <Bar label="Today" window={usage.day} />
          {!usage.limited && (
            <p className="text-xs text-slate-400">
              No usage limits are configured on this server.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}
