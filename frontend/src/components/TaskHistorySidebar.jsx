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
  mobileOpen,
  onCloseMobile,
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
    <>
      {mobileOpen && <div className="history-scrim" onClick={onCloseMobile} />}
      <div className={`neu-raised history-sidebar${mobileOpen ? ' history-sidebar-open' : ''}`}>
        <div className="history-header">
          <h2>Task History</h2>
          <button type="button" className="neu-pressable history-close" onClick={onCloseMobile} aria-label="Close history">✕</button>
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
              <div className="history-item-actions">
                <button type="button" className="neu-pressable history-action" onClick={(e) => toggleFavorite(task, e)} title={task.is_favorite ? 'Unfavorite' : 'Favorite'}>
                  {task.is_favorite ? '★' : '☆'}
                </button>
                <button type="button" className="neu-pressable history-action" onClick={(e) => { e.stopPropagation(); startRename(task) }} title="Rename">✎</button>
                <button type="button" className="neu-pressable history-action" onClick={(e) => toggleArchive(task, e)} title={task.is_archived ? 'Unarchive' : 'Archive'}>
                  {task.is_archived ? '⤴' : '🗄'}
                </button>
                <button type="button" className="neu-pressable history-action history-action-danger" onClick={(e) => remove(task, e)} title="Delete">🗑</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
