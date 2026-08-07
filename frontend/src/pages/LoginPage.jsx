import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import OAuthButtons from '../components/OAuthButtons'
import './AuthPages.css'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const redirectTo = location.state?.from?.pathname || '/dashboard'

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err?.response?.data?.non_field_errors?.[0] || err?.response?.data?.detail || 'Invalid email or password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-shell view-fade-in">
      <div className="neu-raised auth-card anim-fade-up">
        <span className="auth-kicker">Agent Swarm</span>
        <h1>Sign in</h1>

        <OAuthButtons />
        <div className="auth-divider">or</div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-field">
            Email
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="auth-field">
            Password
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button type="submit" className="neu-flat neu-pressable auth-submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="auth-switch">
          No account yet? <Link to="/signup">Sign up</Link>
        </div>
        <Link to="/" className="auth-back">← Back to home</Link>
      </div>
    </div>
  )
}
