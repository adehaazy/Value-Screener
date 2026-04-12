import { ProtectedRoute } from './ProtectedRoute'
import Root from './Root'

/**
 * Root layout wrapped in auth protection.
 * Used as the Component for the "/" route so React Router
 * can reference it as a stable component (not an inline arrow).
 */
export default function ProtectedRoot() {
  return (
    <ProtectedRoute>
      <Root />
    </ProtectedRoute>
  )
}
