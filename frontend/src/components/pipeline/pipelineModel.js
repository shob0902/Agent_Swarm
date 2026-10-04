// Turns a task and its agent runs into what the workflow canvas draws: per-stage state, connector labels, loop usage.
export const STAGES = [
  {
    key: 'analyzer',
    name: 'Analyzer',
    done: 'Repository analyzed',
    activeStatuses: ['analyzing'],
    resource: { kind: 'Tool', name: 'git clone', icon: 'branch' },
    describe:
      'Clones the repository (read-only) and works out its languages, frameworks, and how it installs, builds, tests and lints. No AI is involved in this step.',
  },
  {
    key: 'planner',
    name: 'Planner',
    done: 'Plan created',
    activeStatuses: ['planning'],
    resource: { kind: 'Model', name: 'Groq LLM', icon: 'cpu' },
    describe:
      'Reads your request together with the repository structure and writes an ordered implementation plan, plus the pull request title and summary.',
  },
  {
    key: 'coder',
    name: 'Coder',
    done: 'Code modified',
    activeStatuses: ['coding'],
    resource: { kind: 'Model', name: 'Groq · 2 keys', icon: 'cpu' },
    describe:
      'Rewrites the files the plan names. When tests fail or the Reviewer asks for changes, it runs again with that feedback as its instructions.',
  },
  {
    key: 'tester',
    name: 'Tester',
    done: 'Tests passed',
    activeStatuses: ['testing'],
    resource: { kind: 'Sandbox', name: 'Docker sandbox', icon: 'box' },
    describe:
      "Installs dependencies, then runs the repository's own build, tests and linter in an isolated container with no network access and no secrets. No AI is involved, so the result is objective.",
  },
  {
    key: 'reviewer',
    name: 'Reviewer',
    done: 'Code reviewed',
    activeStatuses: ['review'],
    resource: { kind: 'Model', name: 'Groq LLM', icon: 'cpu' },
    describe:
      'Reviews the whole change like a senior engineer: does it implement the request, follow the conventions, avoid regressions and security problems? Automated safety checks can veto an approval.',
  },
  {
    key: 'github',
    name: 'Pull Request',
    done: 'Pull Request created',
    activeStatuses: ['publishing'],
    resource: { kind: 'Tool', name: 'GitHub API', icon: 'github' },
    describe:
      'Creates a new branch and commit (directly if the token can write to the repo, otherwise through a fork) and opens a pull request. It never touches the default branch and never merges.',
  },
]
export const STAGE_BY_KEY = Object.fromEntries(STAGES.map((s) => [s.key, s]))
export function runsByStage(runs) {
  // Groups the agent runs by stage, keeping their chronological order.
  const grouped = Object.fromEntries(STAGES.map((s) => [s.key, []]))
  for (const run of runs) {
    if (grouped[run.agent_type]) grouped[run.agent_type].push(run)
  }
  return grouped
}
function failedStage(task) {
  // Which stage the task failed at, if it failed.
  if (task.status !== 'failed') return null
  const stage = task.final_result?.stage || task.current_agent
  if (stage === 'clone') return 'analyzer'
  return STAGE_BY_KEY[stage] ? stage : null
}
export function stageState(task, grouped, key) {
  // One of: pending, running, success, retrying, failed, skipped.
  const runs = grouped[key] || []
  const last = runs[runs.length - 1]
  const running = task.is_active && (task.current_agent === key || STAGE_BY_KEY[key].activeStatuses.includes(task.status))
  if (failedStage(task) === key) return 'failed'
  if (key === 'tester') {
    if (running) return 'running'
    if (task.test_status === 'failed') return task.is_active ? 'retrying' : 'failed'
    if (['passed', 'skipped'].includes(task.test_status) && runs.length) return 'success'
  } else if (key === 'reviewer') {
    if (running) return 'running'
    if (task.review_status === 'rejected') return task.is_active ? 'retrying' : 'failed'
    if (task.review_status === 'approved') return 'success'
  } else if (key === 'github') {
    if (running) return 'running'
    if (task.pr_state === 'skipped') return 'skipped'
    if (['open', 'merged', 'closed'].includes(task.pr_state)) return 'success'
  } else {
    if (running) return 'running'
    if (last?.status === 'success') return 'success'
  }
  if (last?.status === 'pending' && task.is_active) return 'running'
  return 'pending'
}
export function triggerState(task) {
  // The trigger node: the task itself.
  if (task.status === 'queued' || task.status === 'pending') return 'running'
  return 'success'
}
function testLabel(task) {
  // "9 passed", "skipped", "failed" -- the connector label out of the Tester.
  const tests = (task.test_results?.checks || []).find((c) => c.category === 'test' && c.summary)
  if (tests) return tests.summary
  if (task.test_status === 'skipped') return 'no test suite'
  return task.test_status || ''
}
export function connectorLabels(task, grouped) {
  // Text on each connector, like n8n's "1 item": what flows from one stage to the next.
  const analyzer = grouped.analyzer.at(-1)?.output || {}
  const stack = (analyzer.frameworks || [])[0] || (analyzer.languages || [])[0] || ''
  const steps = task.plan?.steps?.length
  const coder = grouped.coder.filter((r) => r.status === 'success').at(-1)?.output
  const files = coder?.files?.length
  return {
    trigger: 'repo + request',
    analyzer: stack || '',
    planner: steps ? `${steps} step${steps === 1 ? '' : 's'}` : '',
    coder: files ? `${files} file${files === 1 ? '' : 's'}` : '',
    tester: testLabel(task),
    reviewer: task.review_status === 'approved' ? 'approved' : task.review_status === 'rejected' ? 'rejected' : '',
  }
}
export function loopUsage(task, grouped) {
  // How often each retry loop was taken: Tester -> Coder (test failures) and Reviewer -> Coder (rejections).
  const reviewCycles = task.review_cycles || 0
  const coderRuns = grouped.coder.length
  const testFixes = Math.max(0, coderRuns - 1 - reviewCycles)
  return { testFixes, reviewCycles }
}
export function defaultSelection(task, grouped) {
  // Which node to open when the user hasn't picked one: the live one, the failed one, or the last one reached.
  const running = STAGES.find((s) => stageState(task, grouped, s.key) === 'running')
  if (running) return running.key
  const failed = STAGES.find((s) => stageState(task, grouped, s.key) === 'failed')
  if (failed) return failed.key
  const reached = [...STAGES].reverse().find((s) => grouped[s.key].length)
  return reached ? reached.key : 'trigger'
}
export function formatDuration(ms) {
  // 850 ms -> "0.9s", 75000 -> "1m 15s".
  if (ms == null) return ''
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
}
