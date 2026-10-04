// Pipeline checklist plus the run's facts: current agent, tests, review, branch, commit and the pull request link.
import { useState } from 'react'
import { refreshPullRequest, retryTask } from '../api/client'
import StatusBadge from './StatusBadge'
import './PipelineStatus.css'
const STEPS = [
  { key: 'analyzer', label: 'Repository analyzed', active: ['queued', 'analyzing'] },
  { key: 'planner', label: 'Plan created', active: ['planning'] },
  { key: 'coder', label: 'Code modified', active: ['coding'] },
  { key: 'tester', label: 'Tests passed', active: ['testing'] },
  { key: 'reviewer', label: 'Code reviewed', active: ['review'] },
  { key: 'github', label: 'Pull Request created', active: ['publishing'] },
]
const FAILED_STEP = { clone: 0, analyzer: 0, planner: 1, coder: 2, tester: 3, reviewer: 4, github: 5 }
const AGENT_NAME = { analyzer: 'Repository analysis', planner: 'Planner', coder: 'Coder', tester: 'Tester', reviewer: 'Reviewer', github: 'Pull Request' }
const STALE_QUEUE_MS = 5 * 60 * 1000
function stepStates(task, runs) {
  // Works out done / active / failed / pending for each checklist step from the task and its runs.
  const succeeded = new Set(runs.filter((r) => r.status === 'success').map((r) => r.agent_type))
  const done = [
    succeeded.has('analyzer'),
    succeeded.has('planner'),
    succeeded.has('coder'),
    ['passed', 'skipped'].includes(task.test_status) && succeeded.has('tester'),
    task.review_status === 'approved',
    ['open', 'merged', 'closed'].includes(task.pr_state),
  ]
  const failedAt = task.status === 'failed' ? FAILED_STEP[task.final_result?.stage] ?? FAILED_STEP[task.current_agent] : undefined
  return STEPS.map((step, i) => {
    if (failedAt === i) return 'failed'
    if (done[i]) return 'done'
    if (step.active.includes(task.status)) return 'active'
    return 'pending'
  })
}
function stepLabel(step, task) {
  // Adjusts the wording when tests were skipped or PR creation was switched off.
  if (step.key === 'tester' && task.test_status === 'skipped') return 'Tests skipped (no test suite detected)'
  if (step.key === 'github' && task.pr_state === 'skipped') return 'Pull Request skipped (disabled)'
  return step.label
}
function testSummary(task) {
  // e.g. "pytest: 3 passed · lint: failed".
  const checks = task.test_results?.checks || []
  return checks.map((c) => `${c.name}: ${c.summary || c.status}${!c.required && c.status === 'failed' ? ' (advisory)' : ''}`).join(' · ')
}
function Row({ label, children }) {
  // One label/value line in the facts grid.
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}
export default function PipelineStatus({ task, runs, onTaskChanged, onRetried }) {
  // Renders the checklist, the facts grid, any error, the retry actions and the "View Pull Request" call to action.
  const [refreshing, setRefreshing] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState(null)
  const retry = async (fromStart) => {
    // Re-dispatches the failed task, resuming at the failed stage unless the user asks for a fresh run.
    if (fromStart && !window.confirm('Restart from scratch? The plan, code and test results from this task will be discarded.')) return
    setRetrying(true)
    setRetryError(null)
    try {
      onRetried?.(await retryTask(task.id, fromStart))
    } catch (err) {
      setRetryError(err?.response?.data?.detail || 'Could not restart the task.')
    } finally {
      setRetrying(false)
    }
  }
  const states = stepStates(task, runs)
  const repoUrl = task.github_url?.replace(/\.git$/, '').replace(/\/$/, '')
  // In fork mode the branch and commit live in the fork, not the target repo.
  const viaFork = task.final_result?.pr_mode === 'fork' && task.final_result?.head_repo
  const headUrl = viaFork ? `https://github.com/${task.final_result.head_repo}` : repoUrl
  const stale = task.status === 'queued' && task.dispatched_at && Date.now() - new Date(task.dispatched_at).getTime() > STALE_QUEUE_MS
  const refresh = async () => {
    // Pulls the latest PR state (merged/closed) from GitHub.
    setRefreshing(true)
    try {
      onTaskChanged?.(await refreshPullRequest(task.id))
    } catch {
    } finally {
      setRefreshing(false)
    }
  }
  return (
    <div className="neu-raised pipeline-status anim-fade-up">
      <div className="pipeline-status-head">
        <h2>Pipeline</h2>
        <StatusBadge status={task.status} />
      </div>
      <ol className="pipeline-steps">
        {STEPS.map((step, i) => (
          <li key={step.key} className={`pipeline-step pipeline-step-${states[i]}`}>
            <span className="pipeline-step-icon" aria-hidden="true">
              {states[i] === 'done' ? '✓' : states[i] === 'failed' ? '✕' : states[i] === 'active' ? '' : '○'}
              {states[i] === 'active' && <span className="neu-pulse-dot" style={{ width: 12, height: 12 }} />}
            </span>
            <span>{stepLabel(step, task)}</span>
          </li>
        ))}
      </ol>
      {task.pr_url && (
        <a className="neu-flat neu-pressable pipeline-pr-cta" href={task.pr_url} target="_blank" rel="noreferrer">
          View Pull Request #{task.pr_number} →
        </a>
      )}
      {task.error_message && (
        <div className="neu-inset pipeline-error">
          <strong>Failed{task.final_result?.stage ? ` at ${AGENT_NAME[task.final_result.stage] || task.final_result.stage}` : ''}:</strong> {task.error_message}
        </div>
      )}
      {task.status === 'failed' && task.retry && (
        <div className="pipeline-retry">
          <button type="button" className="neu-flat neu-pressable pipeline-retry-primary" onClick={() => retry(false)} disabled={retrying}>
            {retrying ? 'Restarting…' : task.retry.stage ? `↻ Retry from ${task.retry.label}` : '↻ Retry'}
          </button>
          {task.retry.stage && (
            <button type="button" className="neu-flat neu-pressable pipeline-retry-secondary" onClick={() => retry(true)} disabled={retrying}>
              Restart from scratch
            </button>
          )}
          <span className="pipeline-fact-note">
            {task.retry.stage
              ? `Keeps everything completed before the ${task.retry.label} step.`
              : 'Runs the whole pipeline again.'}
          </span>
          {retryError && <span className="pipeline-fact-note" style={{ color: 'var(--danger)' }}>{retryError}</span>}
        </div>
      )}
      {stale && (
        <div className="neu-inset pipeline-error" style={{ color: 'var(--warning)' }}>
          Still queued after 5 minutes. Check the GitHub Actions tab of the Agent Swarm repository — the runner may be waiting or misconfigured.
        </div>
      )}
      <dl className="pipeline-facts">
        <Row label="Repository">
          <a href={repoUrl} target="_blank" rel="noreferrer">{repoUrl?.replace('https://github.com/', '')}</a>
        </Row>
        <Row label="Current agent">{task.is_active ? AGENT_NAME[task.current_agent] || 'Waiting for runner' : '—'}</Row>
        {task.attempt > 1 && (
          <Row label="Attempt">
            #{task.attempt}
            {task.resume_from && <span className="pipeline-fact-note">resumed at {AGENT_NAME[task.resume_from] || task.resume_from}</span>}
          </Row>
        )}
        <Row label="Executor">{task.executor === 'github_actions' ? 'GitHub Actions' : task.executor || '—'}</Row>
        <Row label="Retries">
          {task.retry_count} Coder retr{task.retry_count === 1 ? 'y' : 'ies'} · {task.review_cycles} review cycle{task.review_cycles === 1 ? '' : 's'}
        </Row>
        <Row label="Tests">
          <StatusBadge status={task.test_status} />
          {testSummary(task) && <span className="pipeline-fact-note">{testSummary(task)}</span>}
        </Row>
        <Row label="Reviewer">
          <StatusBadge status={task.review_status} />
          {task.review_result?.summary && <span className="pipeline-fact-note">{task.review_result.summary}</span>}
        </Row>
        <Row label="Branch">
          {task.branch_name ? (
            <a href={`${headUrl}/tree/${task.branch_name}`} target="_blank" rel="noreferrer">
              <code>{viaFork ? `${task.final_result.head_repo}:` : ''}{task.branch_name}</code>
            </a>
          ) : '—'}
          {task.base_branch && <span className="pipeline-fact-note">from {task.base_branch}</span>}
        </Row>
        <Row label="Commit">
          {task.commit_sha ? (
            <a href={`${headUrl}/commit/${task.commit_sha}`} target="_blank" rel="noreferrer"><code>{task.commit_sha.slice(0, 7)}</code></a>
          ) : '—'}
        </Row>
        <Row label="Pull request">
          <StatusBadge status={task.pr_state} />
          {task.pr_number && (
            <button type="button" className="neu-flat neu-pressable pipeline-refresh" onClick={refresh} disabled={refreshing}>
              {refreshing ? 'Refreshing…' : 'Refresh'}
            </button>
          )}
          {task.final_result?.pr_mode && (
            <span className="pipeline-fact-note">
              {viaFork ? `opened from fork ${task.final_result.head_repo} (no write access to the repo)` : 'opened directly (write access)'}
            </span>
          )}
          {task.pr_error && <span className="pipeline-fact-note">{task.pr_error}</span>}
        </Row>
        {task.workflow_run_url && (
          <Row label="Execution log">
            <a href={task.workflow_run_url} target="_blank" rel="noreferrer">GitHub Actions run →</a>
          </Row>
        )}
      </dl>
      {task.review_result?.issues?.length > 0 && (
        <div className="pipeline-review-list">
          <strong>Reviewer issues</strong>
          <ul>{task.review_result.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
        </div>
      )}
      {task.review_result?.suggestions?.length > 0 && (
        <div className="pipeline-review-list">
          <strong>Reviewer suggestions</strong>
          <ul>{task.review_result.suggestions.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
