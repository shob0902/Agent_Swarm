// Logs panel for the selected canvas node: what the stage does, what it's doing now, and each attempt's inputs and outputs.
import { useEffect, useState } from 'react'
import PipelineIcon from './PipelineIcons'
import StatusBadge from '../StatusBadge'
import { STAGE_BY_KEY, formatDuration, stageState } from './pipelineModel'
import './StageDetails.css'
const KEY_SLOT = { 'coder-a': 'key A', 'coder-b': 'key B' }
const NOW_TEXT = {
  analyzer: { running: 'Cloning the repository and detecting its stack…', pending: 'Starts as soon as the runner picks up the task.' },
  planner: { running: 'Asking the model for an implementation plan…', pending: 'Waits for the repository analysis.' },
  coder: { running: 'Writing the changes…', pending: 'Waits for the plan.', retrying: 'Rewriting the code using the feedback below…' },
  tester: { running: 'Installing dependencies and running the checks in the sandbox…', pending: 'Waits for the Coder.', retrying: 'Checks failed; the Coder is fixing them.' },
  reviewer: { running: 'Reviewing the full change…', pending: 'Waits for passing checks.', retrying: 'Changes requested; the Coder is addressing them.' },
  github: { running: 'Creating the branch, the commit and the pull request…', pending: 'Runs once the Reviewer approves.' },
}
function attemptStatus(stageKey, run) {
  // The badge for one attempt: what it concluded (tests passed/failed, approved/rejected), not just "the agent ran".
  if (run.status === 'pending') return 'running'
  if (run.status !== 'success') return run.status
  if (stageKey === 'tester' && run.output?.status) return run.output.status
  if (stageKey === 'reviewer' && typeof run.output?.approved === 'boolean') return run.output.approved ? 'approved' : 'rejected'
  return 'success'
}
function nowText(key, state, task) {
  // A one-line, plain-English status for the selected stage.
  if (state === 'success') return 'Finished successfully.'
  if (state === 'failed') return task.error_message || 'This step failed.'
  if (state === 'skipped') return 'Skipped: pull request creation is switched off.'
  return NOW_TEXT[key]?.[state] || NOW_TEXT[key]?.pending || ''
}
export default function StageDetails({ stageKey, task, grouped }) {
  // Shows the trigger summary, or the selected stage with its attempts.
  if (stageKey === 'trigger') return <TriggerDetails task={task} />
  const stage = STAGE_BY_KEY[stageKey]
  const runs = grouped[stageKey] || []
  return <StagePanel key={stageKey} stage={stage} runs={runs} task={task} state={stageState(task, grouped, stageKey)} />
}
function StagePanel({ stage, runs, task, state }) {
  // Attempt list on the left, the chosen attempt's details on the right.
  const [picked, setPicked] = useState(null)
  useEffect(() => {
    // Follow the newest attempt as runs arrive, unless the user picked an older one.
    if (picked !== null && picked >= runs.length) setPicked(null)
  }, [runs.length, picked])
  const index = picked ?? runs.length - 1
  const run = runs[index]
  return (
    <section className="stage-details" aria-label={`${stage.name} details`}>
      <header className="stage-details-head">
        <span className={`stage-details-icon stage-state-${state}`}><PipelineIcon name={stage.key} size={18} /></span>
        <h3>{stage.name}</h3>
        <span className="stage-details-resource"><PipelineIcon name={stage.resource.icon} size={13} /> {stage.resource.name}</span>
      </header>
      <p className="stage-details-describe">{stage.describe}</p>
      <p className={`stage-details-now stage-state-${state}`}>
        <strong>Now:</strong> {nowText(stage.key, state, task)}
      </p>
      {runs.length === 0 ? (
        <p className="stage-details-empty">No activity yet for this step.</p>
      ) : (
        <div className="stage-details-body">
          <ol className="stage-attempts" aria-label="Attempts">
            {runs.map((r, i) => (
              <li key={r.id}>
                <button type="button" className={`stage-attempt${i === index ? ' stage-attempt-active' : ''}`} onClick={() => setPicked(i)} aria-pressed={i === index}>
                  <span>Attempt {i + 1}</span>
                  <StatusBadge status={attemptStatus(stage.key, r)} />
                  <small>{formatDuration(r.duration_ms)}</small>
                </button>
              </li>
            ))}
          </ol>
          <div className="stage-run">{run && <RunDetails stageKey={stage.key} run={run} task={task} />}</div>
        </div>
      )}
    </section>
  )
}
function RunDetails({ stageKey, run, task }) {
  // Stage-specific rendering of one attempt, with the raw JSON one click away.
  const out = run.output || {}
  const input = run.input_context || {}
  if (run.status === 'pending') {
    return <p className="stage-details-now stage-state-running"><span className="flow-spinner stage-inline-spinner" /> This attempt is in progress; its results appear here as soon as it finishes.</p>
  }
  return (
    <>
      {out.error && <div className="stage-error"><strong>Error:</strong> {out.error}</div>}
      {stageKey === 'analyzer' && <AnalyzerRun out={out} />}
      {stageKey === 'planner' && <PlannerRun out={out} />}
      {stageKey === 'coder' && <CoderRun out={out} input={input} />}
      {stageKey === 'tester' && <TesterRun out={out} input={input} />}
      {stageKey === 'reviewer' && <ReviewerRun out={out} />}
      {stageKey === 'github' && <GithubRun out={out} task={task} />}
      <details className="stage-raw">
        <summary>Raw input &amp; output</summary>
        <pre>{JSON.stringify({ input: input, output: stripBulky(out) }, null, 2)}</pre>
      </details>
    </>
  )
}
function stripBulky(out) {
  // Drops provider payloads and whole-file contents from the raw view so it stays readable.
  const rest = { ...out }
  delete rest.raw
  delete rest.raw_response
  if (rest.file_diffs) rest.file_diffs = `${rest.file_diffs.length} file(s) -- see the Changes panel`
  return rest
}
function Field({ label, children }) {
  // One labelled value.
  return (
    <div className="stage-field">
      <span className="stage-field-label">{label}</span>
      <div className="stage-field-value">{children}</div>
    </div>
  )
}
function AnalyzerRun({ out }) {
  // Detected stack and the commands the Tester will run.
  return (
    <>
      <Field label="Stack">{[...(out.languages || []), ...(out.frameworks || [])].join(' · ') || 'Not recognised'}</Field>
      {out.package_managers?.length > 0 && <Field label="Package managers">{out.package_managers.join(', ')}</Field>}
      <Field label="Validation plan">
        {out.checks?.length ? (
          <ul className="stage-list">
            {out.checks.map((c) => (
              <li key={c.name}>
                <strong>{c.name}</strong> {c.command?.length ? <code>{c.command.join(' ')}</code> : <em>runs on changed files</em>}
                {!c.required && <span className="stage-tag">advisory</span>}
              </li>
            ))}
          </ul>
        ) : 'No build or test suite detected'}
      </Field>
      {out.base_sha && <Field label="Base commit"><code>{out.base_branch || 'HEAD'} @ {out.base_sha.slice(0, 7)}</code></Field>}
    </>
  )
}
function PlannerRun({ out }) {
  // The plan the Coder will follow.
  const plan = out.plan || {}
  return (
    <>
      {plan.title && <Field label="PR title">{plan.title}</Field>}
      {plan.summary && <Field label="Why">{plan.summary}</Field>}
      {plan.steps?.length > 0 && (
        <Field label={`Plan (${plan.steps.length} steps)`}>
          <ol className="stage-list stage-steps">{plan.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        </Field>
      )}
    </>
  )
}
function CoderRun({ out, input }) {
  // What it was asked to fix (on retries), which files it wrote, and which API key served it.
  return (
    <>
      {input.feedback && (
        <Field label="Instructions from the previous attempt">
          <pre className="stage-pre">{input.feedback.slice(0, 1500)}</pre>
        </Field>
      )}
      <Field label="Files written">
        {out.files?.length ? <ul className="stage-list">{out.files.map((f) => <li key={f}><code>{f}</code></li>)}</ul> : '—'}
      </Field>
      {(out.key_slot || out.malformed_responses > 0) && (
        <Field label="Model call">
          {out.key_slot && <>served by Groq {KEY_SLOT[out.key_slot] || out.key_slot}</>}
          {out.keys_tried?.length > 1 && <> (failed over: {out.keys_tried.map((k) => KEY_SLOT[k] || k).join(' → ')})</>}
          {out.malformed_responses > 0 && <> · {out.malformed_responses} unusable response(s) re-asked</>}
        </Field>
      )}
    </>
  )
}
function TesterRun({ out, input }) {
  // Every check with its result; failing required checks show their log tail.
  const checks = out.checks || []
  return (
    <>
      {input.stack?.length > 0 && <Field label="Stack">{input.stack.join(' · ')}</Field>}
      <Field label="Checks">
        {checks.length === 0 ? (out.summary || 'No checks were run') : (
          <table className="stage-checks">
            <thead><tr><th>Check</th><th>Result</th><th>Details</th><th>Time</th></tr></thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.name}>
                  <td><strong>{c.name}</strong>{!c.required && <span className="stage-tag">advisory</span>}</td>
                  <td><StatusBadge status={c.status === 'error' ? 'failed' : c.status} /></td>
                  <td>{c.summary || (c.exit_code != null ? `exit ${c.exit_code}` : '')}</td>
                  <td>{formatDuration(c.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Field>
      {checks.filter((c) => c.status !== 'passed' && c.status !== 'skipped' && c.logs).map((c) => (
        <details key={`log-${c.name}`} className="stage-raw" open={c.required}>
          <summary>{c.name} output (last lines)</summary>
          <pre>{c.logs.slice(-2500)}</pre>
        </details>
      ))}
    </>
  )
}
const REVIEW_CHECKS = [
  ['implements_request', 'Implements the request'],
  ['follows_conventions', 'Follows repo conventions'],
  ['tests_pass', 'Tests pass'],
  ['unnecessary_changes', 'Unnecessary changes', true],
  ['security_concerns', 'Security concerns', true],
  ['ready_for_review', 'Ready for human review'],
]
function ReviewerRun({ out }) {
  // Verdict, the review checklist, and blocking issues vs. suggestions.
  const checks = out.checks || {}
  return (
    <>
      <Field label="Verdict">
        <StatusBadge status={out.approved ? 'approved' : out.approved === false ? 'rejected' : 'pending'} />
        {out.summary && <span className="stage-inline">{out.summary}</span>}
      </Field>
      {Object.keys(checks).length > 0 && (
        <Field label="Checklist">
          <ul className="stage-checklist">
            {REVIEW_CHECKS.filter(([k]) => k in checks).map(([k, label, inverted]) => {
              const good = inverted ? !checks[k] : !!checks[k]
              return <li key={k} className={good ? 'ok' : 'bad'}><PipelineIcon name={good ? 'check' : 'cross'} size={12} strokeWidth={3} /> {label}</li>
            })}
            {checks.regression_risk && <li className={checks.regression_risk === 'low' ? 'ok' : 'bad'}>Regression risk: {checks.regression_risk}</li>}
          </ul>
        </Field>
      )}
      {out.issues?.length > 0 && <Field label="Blocking issues"><ul className="stage-list">{out.issues.map((i) => <li key={i}>{i}</li>)}</ul></Field>}
      {out.suggestions?.length > 0 && <Field label="Suggestions"><ul className="stage-list">{out.suggestions.map((s) => <li key={s}>{s}</li>)}</ul></Field>}
    </>
  )
}
function GithubRun({ out, task }) {
  // Direct vs. fork decision, and what was created.
  const access = out.access || {}
  return (
    <>
      {out.mode && (
        <Field label="Path taken">
          {out.mode === 'fork'
            ? `Fork: no write access to the repository, so the branch was pushed to ${out.head_repo} and the PR opened from there.`
            : 'Direct: the token can write to the repository, so the branch was created there.'}
        </Field>
      )}
      {access.token_user && (
        <Field label="Access check">
          acting as <code>{access.token_user}</code> · account can push: {access.account_can_push ? 'yes' : 'no'}
          {access.direct_write_denied && ' · token write refused → fell back to fork'}
        </Field>
      )}
      {out.branch && <Field label="Branch"><code>{out.branch}</code></Field>}
      {out.commit_sha && <Field label="Commit"><code>{out.commit_sha.slice(0, 7)}</code></Field>}
      {out.pr_url && <Field label="Pull request"><a href={out.pr_url} target="_blank" rel="noreferrer">#{out.pr_number} — {out.title || 'open on GitHub'} →</a></Field>}
      {out.labels_applied?.length > 0 && <Field label="Labels">{out.labels_applied.join(', ')}</Field>}
      {out.warnings?.length > 0 && <Field label="Warnings"><ul className="stage-list">{out.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Field>}
      {!out.pr_url && task.pr_error && <Field label="Problem">{task.pr_error}</Field>}
    </>
  )
}
function TriggerDetails({ task }) {
  // The task that started the workflow.
  return (
    <section className="stage-details" aria-label="Task details">
      <header className="stage-details-head">
        <span className="stage-details-icon stage-state-success"><PipelineIcon name="trigger" size={18} /></span>
        <h3>Task #{task.id}</h3>
        <span className="stage-details-resource">{task.executor === 'github_actions' ? 'runs on GitHub Actions' : 'runs locally'}</span>
      </header>
      <p className="stage-details-describe">
        Your request starts the workflow. The task is queued, picked up by a runner, and flows through each stage from left to right. Click any node to see what it did.
      </p>
      <Field label="Request"><span className="stage-request">{task.description}</span></Field>
      <Field label="Repository"><a href={task.github_url} target="_blank" rel="noreferrer">{task.github_url?.replace('https://github.com/', '')}</a></Field>
      {task.attempt > 1 && <Field label="Attempt">#{task.attempt}{task.resume_from ? ` (resumed at ${STAGE_BY_KEY[task.resume_from]?.name || task.resume_from})` : ''}</Field>}
    </section>
  )
}
