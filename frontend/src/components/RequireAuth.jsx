// Route guard that waits for the session check, then either renders the page or redirects to login.
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
export default function RequireAuth({ children }) {
  // Shows a small spinner while the session is still being checked.
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <div className="neu-pulse-dot" style={{ width: 16, height: 16 }} />
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}
