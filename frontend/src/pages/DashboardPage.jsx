import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTasks } from '../api/client'
import TaskForm from '../components/TaskForm'
import TaskHistorySidebar from '../components/TaskHistorySidebar'
import AgentTrace from '../components/AgentTrace'
import UserMenu from '../components/UserMenu'

const TASK_LIST_POLL_MS = 3000

export default function DashboardPage({ theme, onToggleTheme }) {
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all') // 'all' | 'favorite' | 'archived'
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
        // transient poll failure -- next tick retries
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
    setTasks((prev) => {
      // a favorite/archive toggle can make a task drop out of the current
      // filter (e.g. archiving while viewing "Recent") -- drop it locally
      // rather than waiting for the next poll to notice.
      const stillMatches = filter === 'all' || (filter === 'favorite' && updated.is_favorite) || (filter === 'archived' && updated.is_archived)
      if (!stillMatches) return prev.filter((t) => t.id !== updated.id)
      return prev.map((t) => (t.id === updated.id ? updated : t))
    })
  }

  const handleTaskDeleted = (id) => {
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
          <AgentTrace taskId={selectedId} taskStatus={selectedTask?.status} theme={theme} />
        </div>
      </main>
    </div>
  )
}
