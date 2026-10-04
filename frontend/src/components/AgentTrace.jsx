// Live view of one task: pipeline status, the agent execution log, and the cumulative diff. Polls while the run is active.
import { useEffect, useMemo, useState } from 'react'
import { getTask } from '../api/client'
import StatusBadge from './StatusBadge'
import DiffViewer from './DiffViewer'
import PipelineStatus from './PipelineStatus'
const AGENT_LABEL = {
  analyzer: 'Repository Analysis',
  planner: 'Planner',
  coder: 'Coder',
  tester: 'Tester',
  reviewer: 'Reviewer',
  github: 'GitHub PR',
}
const POLL_MS = 2000
const KEY_SLOT_LABEL = { 'coder-a': 'key A', 'coder-b': 'key B' }
function providerLabel(run) {
  // Builds the "via groq · key A" caption showing which key served the run.
  const slot = KEY_SLOT_LABEL[run.output?.key_slot]
  return slot ? `${run.provider} · ${slot}` : run.provider
}
function runCaption(run) {
  // One-line summary of a run's result shown under its name.
  const out = run.output || {}
  if (out.error) return out.error
  if (run.agent_type === 'analyzer') return out.summary
  if (run.agent_type === 'planner') return out.plan?.title || (out.plan?.steps ? `${out.plan.steps.length} steps` : '')
  if (run.agent_type === 'coder') return out.files?.length ? `Changed ${out.files.join(', ')}` : ''
  if (run.agent_type === 'tester') return out.summary
  if (run.agent_type === 'reviewer') return out.summary || (out.approved ? 'Approved' : out.approved === false ? 'Changes requested' : '')
  if (run.agent_type === 'github') return out.pr_url ? `Opened ${out.pr_url}` : ''
  return ''
}
function cumulativeDiffs(runs) {
  // Merges every successful Coder attempt: original content from the first touch, final content from the last.
  const byPath = new Map()
  for (const run of runs) {
    if (run.agent_type !== 'coder' || run.status !== 'success') continue
    for (const d of run.output?.file_diffs || []) {
      const prev = byPath.get(d.path)
      byPath.set(d.path, { path: d.path, old_content: prev ? prev.old_content : d.old_content, new_content: d.new_content })
    }
  }
  return [...byPath.values()].filter((d) => d.old_content !== d.new_content)
}
export default function AgentTrace({ taskId, theme, onTaskChanged }) {
  // Loads the task with its runs, keeps polling while it's active, and renders status, log and diff.
  const [task, setTask] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  useEffect(() => {
    if (!taskId) {
      setTask(null)
      return undefined
    }
    let cancelled = false
    let timer = null
    const fetchTask = async () => {
      try {
        const data = await getTask(taskId)
        if (cancelled) return
        setTask(data)
        setLoadError(null)
        onTaskChanged?.(data)
        if (data.is_active) timer = setTimeout(fetchTask, POLL_MS)
      } catch (err) {
        if (cancelled) return
        setLoadError(err?.response?.status === 404 ? 'Task not found.' : 'Could not load this task — retrying…')
        if (err?.response?.status !== 404) timer = setTimeout(fetchTask, POLL_MS * 2)
      }
    }
    setTask((prev) => (prev?.id === taskId ? prev : null))
    fetchTask()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // onTaskChanged is intentionally not a dependency: a new callback identity must not restart polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, reloadKey])
  const runs = useMemo(() => task?.runs || [], [task])
  const fileDiffs = useMemo(() => cumulativeDiffs(runs), [runs])
  if (!taskId) {
    return (
      <div className="neu-raised" style={{ padding: 24 }}>
        <p style={{ color: 'var(--text-muted)', margin: 0 }}>Select a task, or start a new one, to see its pipeline.</p>
      </div>
    )
  }
  if (!task) {
    return (
      <div className="neu-raised" style={{ padding: 24 }}>
        <p style={{ color: loadError ? 'var(--danger)' : 'var(--text-muted)', margin: 0 }}>{loadError || 'Loading…'}</p>
      </div>
    )
  }
  return (
    <div className="trace-layout">
      <PipelineStatus
        key={task.id}
        task={task}
        runs={runs}
        onTaskChanged={(t) => { setTask((prev) => ({ ...prev, ...t })); onTaskChanged?.(t) }}
        onRetried={(t) => { setTask((prev) => ({ ...prev, ...t })); onTaskChanged?.(t); setReloadKey((k) => k + 1) }}
      />
      <div className="neu-raised trace-log">
        <h2 style={{ marginTop: 0, marginBottom: 4 }}>Execution Log</h2>
        <p className="trace-log-subtitle">{task.title || task.display_title || `Task #${taskId}`}</p>
        {runs.length === 0 && (
          <p style={{ color: 'var(--text-muted)' }}>
            {task.status === 'queued' ? 'Waiting for the runner to pick up the task…' : 'Waiting for the pipeline to start…'}
          </p>
        )}
        <div style={{ position: 'relative', paddingLeft: 24 }}>
          <div
            style={{
              position: 'absolute',
              left: 8,
              top: 6,
              bottom: 6,
              width: 2,
              background: 'var(--shadow-dark)',
            }}
          />
          {runs.map((run, i) => (
            <div
              key={run.id}
              className="anim-fade-up"
              style={{ position: 'relative', marginBottom: 16, animationDelay: `${Math.min(i, 8) * 0.06}s` }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: -24,
                  top: 6,
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  background: 'var(--base)',
                  boxShadow: '2px 2px 4px var(--shadow-dark), -2px -2px 4px var(--shadow-light)',
                }}
              >
                {run.status === 'pending' && <div className="neu-pulse-dot" style={{ width: 12, height: 12 }} />}
              </div>
              <button
                className="neu-flat neu-pressable"
                onClick={() => setExpanded(expanded === run.id ? null : run.id)}
                style={{ width: '100%', maxWidth: '100%', minWidth: 0, textAlign: 'left', padding: '12px 16px' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flexWrap: 'wrap' }}>
                    <strong>{AGENT_LABEL[run.agent_type] || run.agent_type}</strong>
                    {run.retry_count > 0 && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>attempt {run.retry_count + 1}</span>
                    )}
                    {run.provider && run.provider !== 'none' && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>via {providerLabel(run)}</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {run.duration_ms != null && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{(run.duration_ms / 1000).toFixed(1)} s</span>
                    )}
                    <StatusBadge status={run.status} />
                  </div>
                </div>
                {runCaption(run) && (
                  <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
                    {runCaption(run)}
                  </div>
                )}
                {expanded === run.id && (
                  <pre
                    className="neu-inset"
                    style={{
                      marginTop: 10,
                      padding: 12,
                      fontSize: 12,
                      maxHeight: 300,
                      overflowY: 'auto',
                      whiteSpace: 'pre-wrap',
                      overflowWrap: 'anywhere',
                      wordBreak: 'break-word',
                      maxWidth: '100%',
                      boxSizing: 'border-box',
                    }}
                  >
                    {JSON.stringify(run.output, null, 2)}
                  </pre>
                )}
              </button>
            </div>
          ))}
        </div>
      </div>
      {fileDiffs.length > 0 && (
        <div className="neu-raised anim-fade-up trace-changes">
          <h2 style={{ marginTop: 0 }}>Changes</h2>
          <DiffViewer fileDiffs={fileDiffs} theme={theme} />
        </div>
      )}
    </div>
  )
}
