// Form for starting a run: the GitHub repository to improve plus the improvement request.
import { useState } from 'react'
import { createTask } from '../api/client'
const GITHUB_URL_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+?(\.git)?\/?$/
const labelStyle = { display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text-secondary)', fontSize: 13 }
function errorText(err) {
  // Flattens a DRF error payload into one readable line.
  const data = err?.response?.data
  if (!data) return 'Failed to start the agent'
  if (typeof data === 'string') return data
  return Object.values(data).flat().join(' ')
}
export default function TaskForm({ onCreated }) {
  // Holds the field values and the submit state for the new-run form.
  const [githubUrl, setGithubUrl] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const handleSubmit = async (e) => {
    // Validates the repo URL, creates the task (which dispatches the pipeline), then clears the form.
    e.preventDefault()
    if (!description.trim() || !githubUrl.trim()) return
    if (!GITHUB_URL_RE.test(githubUrl.trim())) {
      setError('Must be a public GitHub repository URL, e.g. https://github.com/owner/repo')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const task = await createTask({ github_url: githubUrl.trim(), description: description.trim() })
      setDescription('')
      setGithubUrl('')
      onCreated?.(task)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSubmitting(false)
    }
  }
  return (
    <form onSubmit={handleSubmit} className="neu-raised" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 style={{ margin: 0 }}>New Improvement</h2>
      <label style={labelStyle}>
        GitHub repository URL
        <input
          type="url"
          placeholder="https://github.com/owner/repo"
          value={githubUrl}
          onChange={(e) => setGithubUrl(e.target.value)}
          required
        />
      </label>
      <label style={labelStyle}>
        Improvement request
        <textarea
          rows={4}
          placeholder="e.g. Improve API performance and add appropriate caching."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
        />
      </label>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
        The agents work on a new branch and open a pull request for you to review. Nothing is merged automatically.
      </p>
      {error && <div style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</div>}
      <button type="submit" disabled={submitting} className="neu-flat neu-pressable" style={{ padding: '10px 20px', minHeight: 44, alignSelf: 'flex-start', color: 'var(--accent)', fontWeight: 600 }}>
        {submitting ? 'Starting…' : 'Start Agent'}
      </button>
    </form>
  )
}
