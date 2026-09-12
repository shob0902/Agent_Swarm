// Page the OAuth provider redirects back to; swaps the returned code for a session.
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { redirectUriFor } from '../auth/oauth'
import './AuthPages.css'
export default function AuthCallbackPage() {
  // Exchanges the single-use code exactly once, then either lands on the dashboard or shows the error.
  const { provider } = useParams()
  const [searchParams] = useSearchParams()
  const { loginWithProvider } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const exchanged = useRef(false)
  useEffect(() => {
    const code = searchParams.get('code')
    const providerError = searchParams.get('error')
    if (providerError) {
      setError(`${provider} sign-in was cancelled or denied.`)
      return
    }
    if (!code) {
      setError('Missing authorization code from the provider.')
      return
    }
    if (exchanged.current) return
    exchanged.current = true
    loginWithProvider(provider, code, redirectUriFor(provider))
      .then(() => navigate('/dashboard', { replace: true }))
      .catch(() => setError(`Could not complete ${provider} sign-in. Please try again.`))
  }, [provider, searchParams, loginWithProvider, navigate])
  return (
    <div className="auth-shell view-fade-in">
      <div className="neu-raised auth-card anim-fade-up">
        <span className="auth-kicker">Agent Swarm</span>
        {error ? (
          <>
            <h1>Sign-in failed</h1>
            <div className="auth-error">{error}</div>
            <Link to="/login" className="auth-switch">← Back to sign in</Link>
          </>
        ) : (
          <>
            <h1>Signing you in…</h1>
            <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0' }}>
              <div className="neu-pulse-dot" style={{ width: 16, height: 16 }} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
