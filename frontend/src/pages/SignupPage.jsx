// Account creation page offering both the OAuth providers and an email/password form.
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import OAuthButtons from '../components/OAuthButtons'
import './AuthPages.css'
function firstError(data) {
  // Flattens a DRF field-error response down to a single message to show.
  if (!data) return null
  for (const key of ['non_field_errors', 'email', 'password1', 'password2', 'detail']) {
    if (data[key]?.[0]) return data[key][0]
    if (key === 'detail' && typeof data.detail === 'string') return data.detail
  }
  return 'Could not create an account'
}
export default function SignupPage() {
  // Holds the three form fields and drops the user on the dashboard once the account is made.
  const { signupWithEmail } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password1, setPassword1] = useState('')
  const [password2, setPassword2] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const handleSubmit = async (e) => {
    // Submits the signup and surfaces the first validation error if it is rejected.
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await signupWithEmail(email, password1, password2)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(firstError(err?.response?.data))
    } finally {
      setSubmitting(false)
    }
  }
  return (
    <div className="auth-shell view-fade-in">
      <div className="neu-raised auth-card anim-fade-up">
        <span className="auth-kicker">Agent Swarm</span>
        <h1>Create your account</h1>
        <OAuthButtons />
        <div className="auth-divider">or</div>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-field">
            Email
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="auth-field">
            Password
            <input type="password" autoComplete="new-password" required value={password1} onChange={(e) => setPassword1(e.target.value)} />
          </label>
          <label className="auth-field">
            Confirm password
            <input type="password" autoComplete="new-password" required value={password2} onChange={(e) => setPassword2(e.target.value)} />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button type="submit" className="neu-flat neu-pressable auth-submit" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Sign up'}
          </button>
        </form>
        <div className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
        <Link to="/" className="auth-back">← Back to home</Link>
      </div>
    </div>
  )
}
