import { useState } from 'react'
import { createTask } from '../api/client'

const GITHUB_URL_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/

export default function TaskForm({ onCreated }) {
  const [description, setDescription] = useState('')
  const [githubUrl, setGithubUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!description.trim() || !githubUrl.trim()) return
    if (!GITHUB_URL_RE.test(githubUrl.trim())) {
      setError('Must be a public GitHub repo URL, e.g. https://github.com/owner/repo')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const task = await createTask({ description, github_url: githubUrl.trim() })
      setDescription('')
      setGithubUrl('')
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
        GitHub repo URL
        <input
          type="url"
          placeholder="https://github.com/owner/repo"
          value={githubUrl}
          onChange={(e) => setGithubUrl(e.target.value)}
          required
        />
      </label>

      {error && <div style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</div>}

      <button type="submit" disabled={submitting} className="neu-flat neu-pressable" style={{ padding: '10px 20px', minHeight: 44, alignSelf: 'flex-start', color: 'var(--accent)', fontWeight: 600 }}>
        {submitting ? 'Submitting…' : 'Run Agent Swarm'}
      </button>
    </form>
  )
}
