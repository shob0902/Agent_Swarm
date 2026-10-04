// Public landing page explaining what the swarm does, with the sign-in and get-started links.
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import ThemeToggle from './ThemeToggle'
import './LandingPage.css'
const STEPS = [
  { agent: 'Analyzer', provider: 'deterministic · no LLM', blurb: 'Clones the repository and detects its stack — Python, Node.js or TypeScript — plus how it installs, builds, tests and lints.' },
  { agent: 'Planner', provider: 'Groq', blurb: 'Breaks your task description into an ordered, concrete implementation plan.' },
  { agent: 'Coder', provider: 'Groq · 2 keys', blurb: 'Rewrites the files the plan calls for, straight into your repo. The highest-volume agent, so it gets two keys and rotates between them least-recently-used first, cooling off any key that hits its rate limit.' },
  { agent: 'Tester', provider: 'sandboxed · no LLM', blurb: 'Installs dependencies, then runs your real build, test suite and linter in an isolated, network-disabled container. Failures go straight back to the Coder.' },
  { agent: 'Reviewer', provider: 'Groq', blurb: 'Reviews the change for correctness, conventions, regressions, unnecessary edits and security issues — rejecting it back to the Coder when needed.' },
  { agent: 'Pull Request', provider: 'GitHub', blurb: 'Pushes a new branch, commits the validated change, and opens a pull request with the plan, test results and review. Never merges, never touches your default branch.' },
]
export default function LandingPage({ theme, onToggleTheme }) {
  // Renders the hero, the four agent cards and the theme toggle, sending the user on to signup or the dashboard.
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
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>
      <section className="landing-hero anim-fade-up" style={{ animationDelay: '0.08s' }}>
        <h1>Autonomous Coding Agent Swarm</h1>
        <p>
          Hand it a public GitHub repository and an improvement request. Cooperating agents —
          Planner, Coder, Tester, and Reviewer — plan the change, write it, validate it in an
          isolated sandbox, retry on failure, and open a reviewed pull request for you to merge. Every decision is logged and visible in a live agent trace,
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
        <p>Runs on GitHub Actions · sandboxed execution (Docker, no network) · bounded retries on test failure and review rejection · human review before every merge</p>
      </section>
    </div>
  )
}
