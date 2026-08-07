import { useState } from 'react'
import { createTask } from '../api/client'

export default function TaskForm({ onCreated }) {
  const [description, setDescription] = useState('')
  const [repoPath, setRepoPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!description.trim() || !repoPath.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const task = await createTask({ description, repo_path: repoPath })
      setDescription('')
      setRepoPath('')
      onCreated?.(task)
    } catch (err) {
      setError(err?.response?.data ? JSON.stringify(err.response.data) : 'Failed to create task')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="neu-raised" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 style={{ margin: 0 }}>New Task</h2>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text-secondary)', fontSize: 13 }}>
        Description
        <textarea
          rows={3}
          placeholder="e.g. Add input validation to the /signup endpoint"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text-secondary)', fontSize: 13 }}>
        Repo path
        <input
          type="text"
          placeholder="C:\path\to\local\git\repo"
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          required
        />
      </label>

      {error && <div style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</div>}

      <button type="submit" disabled={submitting} className="neu-flat neu-pressable" style={{ padding: '10px 20px', alignSelf: 'flex-start', color: 'var(--accent)', fontWeight: 600 }}>
        {submitting ? 'Submitting…' : 'Run Agent Swarm'}
      </button>
    </form>
  )
}
