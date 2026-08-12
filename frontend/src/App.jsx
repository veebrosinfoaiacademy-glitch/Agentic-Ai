import { Navigate, Route, Routes } from 'react-router-dom'

import AppLayout from './components/layout/AppLayout'
import { RequireAuth, RequireGuest } from './components/layout/RouteGuards'
import { AuthProvider } from './context/AuthContext'
import ContentAgent from './pages/ContentAgent'
import Dashboard from './pages/Dashboard'
import DeveloperAgent from './pages/DeveloperAgent'
import Documents from './pages/Documents'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Register from './pages/Register'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />

        {/* Signed-in users are bounced away from these. */}
        <Route
          path="/login"
          element={
            <RequireGuest>
              <Login />
            </RequireGuest>
          }
        />
        <Route
          path="/register"
          element={
            <RequireGuest>
              <Register />
            </RequireGuest>
          }
        />

        {/* Everything inside the layout requires a session. */}
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/content" element={<ContentAgent />} />
          <Route path="/developer" element={<DeveloperAgent />} />
          <Route path="/documents" element={<Documents />} />
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </AuthProvider>
  )
}
