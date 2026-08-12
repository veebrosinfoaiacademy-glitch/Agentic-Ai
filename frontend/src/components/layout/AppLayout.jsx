import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../../context/useAuth'
import { Button } from '../common'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: '◆' },
  { to: '/content', label: 'Content Agent', icon: '✎' },
  { to: '/developer', label: 'Developer Agent', icon: '⌘' },
  { to: '/documents', label: 'Documents', icon: '⬒' },
  { to: '/conversations', label: 'Conversations', icon: '☰' },
]

function NavItems({ onNavigate }) {
  return (
    <nav aria-label="Main" className="flex-1 space-y-1 px-3">
      {NAV_ITEMS.map(({ to, label, icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 ${
              isActive
                ? 'bg-slate-800 text-white'
                : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
            }`
          }
        >
          <span aria-hidden="true" className="w-4 text-center text-slate-400">
            {icon}
          </span>
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

function SidebarContent({ onNavigate }) {
  const { user, logout } = useAuth()

  return (
    <div className="flex h-full flex-col bg-slate-900 py-5">
      <div className="px-5 pb-5">
        <p className="text-sm font-semibold text-white">AI Productivity</p>
        <p className="text-xs text-slate-400">Agents Platform</p>
      </div>

      <NavItems onNavigate={onNavigate} />

      <div className="mt-auto border-t border-slate-800 px-5 pt-4">
        {/* Long emails must not widen the sidebar. */}
        <p className="truncate text-xs text-slate-400" title={user?.email}>
          {user?.email}
        </p>
        <Button
          variant="ghost"
          onClick={logout}
          className="mt-2 w-full justify-start px-0 text-slate-300 hover:bg-transparent hover:text-white"
        >
          Sign out
        </Button>
      </div>
    </div>
  )
}

export default function AppLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()

  // Close the drawer on navigation, otherwise it covers the page it opened.
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 lg:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-900/50"
            onClick={() => setMobileNavOpen(false)}
          />
          <div className="relative h-full w-64 shadow-xl">
            <SidebarContent onNavigate={() => setMobileNavOpen(false)} />
          </div>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6">
          <Button
            variant="ghost"
            className="lg:hidden"
            aria-expanded={mobileNavOpen}
            aria-label="Open navigation"
            onClick={() => setMobileNavOpen(true)}
          >
            <span aria-hidden="true">☰</span>
          </Button>
          <p className="truncate text-sm font-medium text-slate-700">
            {NAV_ITEMS.find((item) => location.pathname.startsWith(item.to))?.label ??
              'Overview'}
          </p>
        </header>

        {/* min-w-0 stops wide children from forcing horizontal page scroll. */}
        <main className="mx-auto min-w-0 max-w-5xl px-4 py-6 sm:px-6 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
