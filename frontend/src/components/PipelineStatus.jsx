// Pipeline card: the n8n-style workflow canvas, the selected node's logs, retry actions, and the run's facts.
import { useMemo, useState } from 'react'
import { refreshPullRequest, retryTask } from '../api/client'
import StatusBadge from './StatusBadge'
import PipelineGraph from './pipeline/PipelineGraph'
import StageDetails from './pipeline/StageDetails'
import { defaultSelection, runsByStage } from './pipeline/pipelineModel'
import './PipelineStatus.css'
const AGENT_NAME = { analyzer: 'Repository analysis', planner: 'Planner', coder: 'Coder', tester: 'Tester', reviewer: 'Reviewer', github: 'Pull Request' }
const STALE_QUEUE_MS = 5 * 60 * 1000
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
  // Renders the canvas + logs panel, any error, the retry actions, the "View Pull Request" call to action and the facts grid.
  const [refreshing, setRefreshing] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState(null)
  const [pickedNode, setPickedNode] = useState(null)
  const grouped = useMemo(() => runsByStage(runs), [runs])
  // Follow the live/failed node automatically until the user clicks one.
  const selectedNode = pickedNode ?? defaultSelection(task, grouped)
  const retry = async (fromStart) => {
    // Re-dispatches the failed task, resuming at the failed stage unless the user asks for a fresh run.
    if (fromStart && !window.confirm('Restart from scratch? The plan, code and test results from this task will be discarded.')) return
    setRetrying(true)
    setRetryError(null)
    try {
      onRetried?.(await retryTask(task.id, fromStart))
      setPickedNode(null)
    } catch (err) {
      setRetryError(err?.response?.data?.detail || 'Could not restart the task.')
    } finally {
      setRetrying(false)
    }
  }
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
      <p className="pipeline-hint">Each node is an agent. Data flows left to right, and the arcs are the retry loops. Click a node to see what it did.</p>
      <PipelineGraph task={task} grouped={grouped} selected={selectedNode} onSelect={setPickedNode} />
      <StageDetails stageKey={selectedNode} task={task} grouped={grouped} />
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
      {task.retry && (
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
          {task.retry ? ' It looks abandoned, so you can retry it above.' : ' A Retry option appears after 10 minutes if the runner never reports back.'}
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
    </div>
  )
}
