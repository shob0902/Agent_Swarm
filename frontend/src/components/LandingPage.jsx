import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './LandingPage.css'

const STEPS = [
  { agent: 'Planner', provider: 'Gemini', blurb: 'Breaks your task description into an ordered, concrete implementation plan.' },
  { agent: 'Coder', provider: 'Gemini', blurb: 'Rewrites the files the plan calls for, straight into your repo.' },
  { agent: 'Tester', provider: 'sandboxed · no LLM', blurb: 'Runs your real test suite in an isolated, network-disabled container and parses the result.' },
  { agent: 'Reviewer', provider: 'Groq', blurb: 'Gives the final diff a fast sanity check against the plan before marking the task done.' },
]

export default function LandingPage({ theme, onToggleTheme }) {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="landing view-fade-in">
      <header className="landing-header anim-fade-up">
        <span className="landing-kicker">Multi-agent orchestration</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {!isAuthenticated && (
            <Link to="/login" className="neu-flat neu-pressable" style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}>
              Sign in
            </Link>
          )}
          <button
            className="neu-flat neu-pressable"
            onClick={onToggleTheme}
            style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}
          >
            {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
          </button>
        </div>
      </header>

      <section className="landing-hero anim-fade-up" style={{ animationDelay: '0.08s' }}>
        <h1>Autonomous Coding Agent Swarm</h1>
        <p>
          Hand it a task description and a public GitHub repo. Four cooperating agents —
          Planner, Coder, Tester, and Reviewer — plan the change, write it, run your
          real test suite in an isolated sandbox, retry on failure, and hand back a
          reviewed diff. Every decision is logged and visible in a live agent trace,
          private to your account.
        </p>
        <button
          className="neu-flat neu-pressable landing-cta"
          onClick={() => navigate(isAuthenticated ? '/dashboard' : '/signup')}
        >
          {isAuthenticated ? 'Open Dashboard →' : 'Get Started →'}
        </button>
      </section>

      <section className="landing-steps">
        {STEPS.map((step, i) => (
          <div
            key={step.agent}
            className="neu-raised landing-step anim-fade-up"
            style={{ animationDelay: `${0.16 + i * 0.08}s` }}
          >
            <span className="landing-step-index">{i + 1}</span>
            <h3>{step.agent}</h3>
            <span className="landing-step-provider">{step.provider}</span>
            <p>{step.blurb}</p>
          </div>
        ))}
      </section>

      <section className="landing-footnote anim-fade-up" style={{ animationDelay: '0.5s' }}>
        <p>Sandboxed execution (Docker, no network) · Django + Celery orchestrator · bounded retries on test failure</p>
      </section>
    </div>
  )
}
