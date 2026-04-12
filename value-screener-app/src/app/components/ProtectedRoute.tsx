import React from 'react'
import { Navigate, useLocation } from 'react-router'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../AuthContext'

/* ============================================================
   Protected Route — Auth guard for routes
   ============================================================ */

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  // Show loading spinner while checking auth
  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center min-h-screen"
        style={{ backgroundColor: '#F5F3EF' }}
      >
        <div className="text-center">
          <div
            className="font-mono uppercase tracking-widest mb-6"
            style={{ color: '#6B7F5E' }}
          >
            Ben's Shed
          </div>
          <Loader2 className="w-6 h-6 animate-spin mx-auto" style={{ color: '#6B7F5E' }} />
        </div>
      </div>
    )
  }

  // Not authenticated — redirect to login
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  // Authenticated but must change passcode (except if already on that page)
  if (user?.must_change_passcode && location.pathname !== '/change-passcode') {
    return <Navigate to="/change-passcode" replace />
  }

  // All checks passed — render children
  return <>{children}</>
}
