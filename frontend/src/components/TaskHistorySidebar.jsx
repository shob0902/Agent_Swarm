// Sidebar listing past tasks with search, filters and the rename, favorite, archive and delete actions.
import { useState } from 'react'
import { archiveTask, deleteTask, favoriteTask, renameTask } from '../api/client'
import StatusBadge from './StatusBadge'
import './TaskHistorySidebar.css'
const FILTERS = [
  { key: 'all', label: 'Recent' },
  { key: 'favorite', label: 'Favorites' },
  { key: 'archived', label: 'Archived' },
]
export default function TaskHistorySidebar({
  tasks,
  selectedId,
  onSelect,
  search,
  onSearchChange,
  filter,
  onFilterChange,
  onTaskUpdated,
  onTaskDeleted,
}) {
  // Keeps track of which row is being renamed or is mid-request, and renders the list.
  const [editingId, setEditingId] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [busyId, setBusyId] = useState(null)
  const startRename = (task) => {
    // Puts a row into edit mode, seeded with its current title.
    setEditingId(task.id)
    setEditValue(task.title || task.description.slice(0, 60))
  }
  const commitRename = async (task) => {
    // Saves the edited title, quietly leaving the old one in place if the save fails.
    setEditingId(null)
    const title = editValue.trim()
    if (!title || title === (task.title || '')) return
    try {
      const updated = await renameTask(task.id, title)
      onTaskUpdated(updated)
    } catch {
    }
  }
  const toggleFavorite = async (task, e) => {
    // Flips the task's favorite flag on the server.
    e.stopPropagation()
    setBusyId(task.id)
    try {
      onTaskUpdated(await favoriteTask(task.id))
    } finally {
      setBusyId(null)
    }
  }
  const toggleArchive = async (task, e) => {
    // Flips the task's archived flag on the server.
    e.stopPropagation()
    setBusyId(task.id)
    try {
      onTaskUpdated(await archiveTask(task.id))
    } finally {
      setBusyId(null)
    }
  }
  const remove = async (task, e) => {
    // Asks for confirmation, then deletes the task for good.
    e.stopPropagation()
    if (!window.confirm(`Delete "${task.title || task.display_title}"? This can't be undone.`)) return
    setBusyId(task.id)
    try {
      await deleteTask(task.id)
      onTaskDeleted(task.id)
    } finally {
      setBusyId(null)
    }
  }
  return (
      <div className="neu-raised history-sidebar">
        <div className="history-header">
          <h2>Task History</h2>
        </div>
        <input
          type="search"
          placeholder="Search tasks…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="history-search"
        />
        <div className="history-filters">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`neu-pressable history-filter-chip${filter === f.key ? ' history-filter-chip-active' : ''}`}
              onClick={() => onFilterChange(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="history-list">
          {tasks.length === 0 && <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No tasks yet — submit one above.</p>}
          {tasks.map((task, i) => (
            <div
              key={task.id}
              className={`anim-fade-up history-item ${task.id === selectedId ? 'neu-inset' : 'neu-flat'}`}
              style={{ animationDelay: `${Math.min(i, 8) * 0.04}s`, opacity: busyId === task.id ? 0.6 : 1 }}
              onClick={() => onSelect(task.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(task.id) }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="history-item-top">
                <StatusBadge status={task.status} />
              </div>
              {editingId === task.id ? (
                <input
                  autoFocus
                  className="history-rename-input"
                  value={editValue}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={() => commitRename(task)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(task)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                />
              ) : (
                <div className="history-item-title">{task.title || task.display_title}</div>
              )}
              <div className="history-item-repo">{task.github_url}</div>
              {task.pr_url && (
                <a className="history-item-pr" href={task.pr_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                  PR #{task.pr_number} ↗
                </a>
              )}
              <div className="history-item-actions">
                <button
                  type="button"
                  className={`neu-pressable history-action${task.is_favorite ? ' history-action-active' : ''}`}
                  onClick={(e) => toggleFavorite(task, e)}
                  title={task.is_favorite ? 'Unfavorite' : 'Favorite'}
                  aria-label={task.is_favorite ? 'Unfavorite' : 'Favorite'}
                  aria-pressed={task.is_favorite}
                >
                  <ActionIcon name="star" filled={task.is_favorite} />
                </button>
                <button type="button" className="neu-pressable history-action" onClick={(e) => { e.stopPropagation(); startRename(task) }} title="Rename" aria-label="Rename">
                  <ActionIcon name="pencil" />
                </button>
                <button
                  type="button"
                  className="neu-pressable history-action"
                  onClick={(e) => toggleArchive(task, e)}
                  title={task.is_archived ? 'Unarchive' : 'Archive'}
                  aria-label={task.is_archived ? 'Unarchive' : 'Archive'}
                >
                  <ActionIcon name={task.is_archived ? 'unarchive' : 'archive'} />
                </button>
                <button type="button" className="neu-pressable history-action history-action-danger" onClick={(e) => remove(task, e)} title="Delete" aria-label="Delete">
                  <ActionIcon name="trash" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
  )
}
const ACTION_PATHS = {
  star: 'M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.85L12 16.9l-5.25 2.75 1-5.85L3.5 9.7l5.9-.9z',
  pencil: 'M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17zM14.5 7.5l3 3',
  archive: 'M3.5 5h17v4h-17zM5 9v10h14V9M10 13h4',
  unarchive: 'M3.5 5h17v4h-17zM5 9v10h14V9M12 17v-5M9.5 14.5L12 12l2.5 2.5',
  trash: 'M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6',
}
function ActionIcon({ name, filled = false }) {
  // Outlined 18px icon drawn in the button's text colour, so it follows the theme instead of emoji colours.
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={ACTION_PATHS[name]} />
    </svg>
  )
}
