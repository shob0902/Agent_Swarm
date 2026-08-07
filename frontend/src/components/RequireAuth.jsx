import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// The auth check is a real network call (see AuthContext -- there's no
// local signal for "am I logged in?" besides asking the API), so there's a
// brief window on every hard refresh where we don't yet know. Unlike
// LoadingScreen (a fixed ~2.8s intro flourish), this has to resolve the
// instant the request comes back, so it's a plain inline spinner.
export default function RequireAuth({ children }) {
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
