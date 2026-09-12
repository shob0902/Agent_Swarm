// Main app screen: the new-task form, the task history sidebar and the live agent trace.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTasks } from '../api/client'
import TaskForm from '../components/TaskForm'
import TaskHistorySidebar from '../components/TaskHistorySidebar'
import AgentTrace from '../components/AgentTrace'
import UserMenu from '../components/UserMenu'
const TASK_LIST_POLL_MS = 3000
export default function DashboardPage({ theme, onToggleTheme }) {
  // Polls the task list against the current search and filter, and tracks which task is selected.
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
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
  const selectedTask = tasks.find((t) => t.id === selectedId)
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
          <AgentTrace
            taskId={selectedId}
            taskStatus={selectedTask?.status}
            taskTitle={selectedTask?.title || selectedTask?.display_title}
            theme={theme}
          />
        </div>
      </main>
    </div>
  )
}
