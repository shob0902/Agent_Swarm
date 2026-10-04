// Page the OAuth provider redirects back to; verifies the anti-CSRF state, then swaps the returned code for a session.
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { consumeOAuthState, redirectUriFor } from '../auth/oauth'
import './AuthPages.css'
const PROVIDER_NAME = { google: 'Google', github: 'GitHub' }
function serverMessage(err) {
  // Pulls the most useful message out of a DRF error response.
  const data = err?.response?.data
  if (!data) return null
  if (typeof data === 'string') return data.length < 300 ? data : null
  return data.detail || data.non_field_errors?.[0] || Object.values(data).flat().find((v) => typeof v === 'string') || null
}
export default function AuthCallbackPage() {
  // Exchanges the single-use code exactly once, then either lands where the user started or shows the error.
  const { provider } = useParams()
  const [searchParams] = useSearchParams()
  const { loginWithProvider } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const handled = useRef(false)
  const name = PROVIDER_NAME[provider] || provider
  useEffect(() => {
    // Guarded by a ref: StrictMode runs effects twice, and a code can only be exchanged once.
    if (handled.current) return
    handled.current = true
    const code = searchParams.get('code')
    const providerError = searchParams.get('error')
    const check = consumeOAuthState(provider, searchParams.get('state'))
    if (providerError) {
      setError(providerError === 'access_denied' ? `${name} sign-in was cancelled.` : `${name} returned an error: ${providerError}`)
      return
    }
    if (!PROVIDER_NAME[provider]) {
      setError('Unknown sign-in provider.')
      return
    }
    if (!check.ok) {
      setError('This sign-in link is invalid or has expired. Please start again from the sign-in page.')
      return
    }
    if (!code) {
      setError(`Missing authorization code from ${name}.`)
      return
    }
    // Remove the code from the address bar and history before using it.
    window.history.replaceState(null, '', window.location.pathname)
    loginWithProvider(provider, code, redirectUriFor(provider))
      .then(() => navigate(check.returnTo, { replace: true }))
      .catch((err) => setError(serverMessage(err) || `Could not complete ${name} sign-in. Please try again.`))
  }, [provider, name, searchParams, loginWithProvider, navigate])
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
            <h1>Signing you in with {name}…</h1>
            <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0' }}>
              <div className="neu-pulse-dot" style={{ width: 16, height: 16 }} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
