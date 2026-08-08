import { useEffect, useRef, useState } from 'react'
import { getTaskRuns } from '../api/client'
import StatusBadge from './StatusBadge'
import DiffViewer from './DiffViewer'

const AGENT_LABEL = { planner: 'Planner', coder: 'Coder', tester: 'Tester', reviewer: 'Reviewer' }
const POLL_MS = 2000
const ACTIVE_STATUSES = new Set(['pending', 'planning', 'coding', 'testing', 'review'])
// Coder key slots are named "coder-a"/"coder-b" by the backend key pool
// (backend/agents/services/key_pool.py) -- shown in the trace so a run makes
// it obvious *which* of the Coder's two Groq keys actually served it.
const KEY_SLOT_LABEL = { 'coder-a': 'key A', 'coder-b': 'key B' }

function providerLabel(run) {
  const slot = KEY_SLOT_LABEL[run.output?.key_slot]
  return slot ? `${run.provider} · ${slot}` : run.provider
}

export default function AgentTrace({ taskId, taskStatus, taskTitle, theme }) {
  const [runs, setRuns] = useState([])
  const [expanded, setExpanded] = useState(null)
  const intervalRef = useRef(null)

  useEffect(() => {
    if (!taskId) return
    let cancelled = false

    const fetchRuns = async () => {
      try {
        const data = await getTaskRuns(taskId)
        if (!cancelled) setRuns(data)
      } catch {
        // transient poll failure -- next tick retries, nothing to show the user for a single miss
      }
    }

    fetchRuns()
    clearInterval(intervalRef.current)
    if (ACTIVE_STATUSES.has(taskStatus)) {
      intervalRef.current = setInterval(fetchRuns, POLL_MS)
    }

    return () => {
      cancelled = true
      clearInterval(intervalRef.current)
    }
  }, [taskId, taskStatus])

  if (!taskId) {
    return (
      <div className="neu-raised" style={{ padding: 24 }}>
        <p style={{ color: 'var(--text-muted)', margin: 0 }}>Select a task to see its agent trace.</p>
      </div>
    )
  }

  const lastSuccessfulCoderRun = [...runs].reverse().find((r) => r.agent_type === 'coder' && r.status === 'success')
  const fileDiffs = lastSuccessfulCoderRun?.output?.file_diffs

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="neu-raised" style={{ padding: 24 }}>
        <h2 style={{ marginTop: 0 }}>Agent Trace — {taskTitle || `Task #${taskId}`}</h2>
        {runs.length === 0 && <p style={{ color: 'var(--text-muted)' }}>Waiting for the pipeline to start…</p>}

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
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{run.duration_ms} ms</span>
                    )}
                    <StatusBadge status={run.status} />
                  </div>
                </div>
                {expanded === run.id && (
                  <pre
                    className="neu-inset"
                    style={{
                      marginTop: 10,
                      padding: 12,
                      fontSize: 12,
                      maxHeight: 300,
                      overflowY: 'auto',
                      // Raw agent payloads contain very long unbreakable
                      // tokens (base64 blobs, single-line JSON strings).
                      // pre-wrap alone only breaks at whitespace, so those
                      // would blow the card -- and the whole trace column --
                      // out sideways on expand. `anywhere` lets them break
                      // mid-token so expanding only ever grows downward.
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

      {fileDiffs && (
        <div className="neu-raised anim-fade-up" style={{ padding: 24 }}>
          <h2 style={{ marginTop: 0 }}>Diff</h2>
          <DiffViewer fileDiffs={fileDiffs} theme={theme} />
        </div>
      )}
    </div>
  )
}
