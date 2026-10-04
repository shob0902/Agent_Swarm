// Main app screen: the new-run form, the task history sidebar and the live pipeline view.
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listTasks } from '../api/client'
import TaskForm from '../components/TaskForm'
import TaskHistorySidebar from '../components/TaskHistorySidebar'
import AgentTrace from '../components/AgentTrace'
import UserMenu from '../components/UserMenu'
const TASK_LIST_POLL_MS = 3000
export default function DashboardPage({ theme, onToggleTheme }) {
  // Polls the task list against the current search and filter; the selected task lives in ?task= so a refresh keeps it.
  const [tasks, setTasks] = useState([])
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = Number(searchParams.get('task')) || null
  const setSelectedId = useCallback((idOrUpdater) => {
    // Writes the selection into the URL (replace, so it doesn't spam history).
    setSearchParams((prev) => {
      const current = Number(prev.get('task')) || null
      const id = typeof idOrUpdater === 'function' ? idOrUpdater(current) : idOrUpdater
      const next = new URLSearchParams(prev)
      if (id) next.set('task', String(id))
      else next.delete('task')
      return next
    }, { replace: true })
  }, [setSearchParams])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useEffect(() => {
    let cancelled = false
    const fetchTasks = async () => {
      try {
        const params = {}
        if (search.trim()) params.search = search.trim()
        if (filter === 'favorite') params.favorite = 'true'
        if (filter === 'archived') params.archived = 'true'
        const data = await listTasks(params)
        if (!cancelled) setTasks(data.results ?? data)
      } catch {
      }
    }
    fetchTasks()
    const interval = setInterval(fetchTasks, TASK_LIST_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [search, filter])
  const handleTaskUpdated = (updated) => {
    // Swaps in the updated task, dropping it from the list if it no longer matches the active filter.
    setTasks((prev) => {
      const stillMatches = filter === 'all' || (filter === 'favorite' && updated.is_favorite) || (filter === 'archived' && updated.is_archived)
      if (!stillMatches) return prev.filter((t) => t.id !== updated.id)
      return prev.map((t) => (t.id === updated.id ? updated : t))
    })
  }
  const handleTaskDeleted = (id) => {
    // Removes the deleted task and clears the selection if it was the one showing.
    setTasks((prev) => prev.filter((t) => t.id !== id))
    setSelectedId((prev) => (prev === id ? null : prev))
  }
  const handleDetailLoaded = useCallback((detail) => {
    // Keeps the sidebar row in step with the detail poll, without waiting for the next list refresh.
    setTasks((prev) => prev.map((t) => (t.id === detail.id ? { ...t, ...detail, runs: undefined } : t)))
  }, [])
  return (
    <div className="app-shell view-fade-in">
      <header className="app-header">
        <button
          type="button"
          className="neu-flat neu-pressable app-menu-toggle"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open task history"
        >
          ☰
        </button>
        <Link to="/" className="neu-flat neu-pressable" style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}>
          ← Home
        </Link>
        <div style={{ flex: 1 }} />
        <button
          className="neu-flat neu-pressable"
          onClick={onToggleTheme}
          style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}
        >
          {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
        </button>
        <UserMenu />
      </header>
      <main className="app-grid">
        <div className="app-column">
          <TaskForm onCreated={(task) => { setTasks((prev) => [task, ...prev]); setSelectedId(task.id) }} />
          <TaskHistorySidebar
            tasks={tasks}
            selectedId={selectedId}
            onSelect={(id) => { setSelectedId(id); setSidebarOpen(false) }}
            search={search}
            onSearchChange={setSearch}
            filter={filter}
            onFilterChange={setFilter}
            onTaskUpdated={handleTaskUpdated}
            onTaskDeleted={handleTaskDeleted}
            mobileOpen={sidebarOpen}
            onCloseMobile={() => setSidebarOpen(false)}
          />
        </div>
        <div className="app-column">
          <AgentTrace taskId={selectedId} theme={theme} onTaskChanged={handleDetailLoaded} />
        </div>
      </main>
    </div>
  )
}
