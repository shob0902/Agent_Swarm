// Main app screen: a sidebar (new-run form + task history) and a wide main area for the selected task's pipeline.
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listTasks } from '../api/client'
import TaskForm from '../components/TaskForm'
import TaskHistorySidebar from '../components/TaskHistorySidebar'
import AgentTrace from '../components/AgentTrace'
import UserMenu from '../components/UserMenu'
import ThemeToggle from '../components/ThemeToggle'
import './DashboardPage.css'
const TASK_LIST_POLL_MS = 3000
const COLLAPSED_KEY = 'agent-swarm-sidebar-collapsed'
// Below this width the sidebar is an off-canvas drawer instead of a column (matches DashboardPage.css).
const DRAWER_QUERY = '(max-width: 1023px)'
function readCollapsed() {
  // Remembers whether the desktop sidebar was hidden; storage can be unavailable, so default to shown.
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}
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
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)
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
  useEffect(() => {
    // Escape closes the mobile drawer.
    if (!drawerOpen) return undefined
    const onKey = (e) => e.key === 'Escape' && setDrawerOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])
  const toggleSidebar = () => {
    // On small screens open the drawer; on desktop hide/show the sidebar column and remember the choice.
    if (window.matchMedia(DRAWER_QUERY).matches) {
      setDrawerOpen(true)
      return
    }
    setCollapsed((prev) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, prev ? '0' : '1')
      } catch {
      }
      return !prev
    })
  }
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
  const selectTask = (id) => {
    // Shows a task and closes the drawer on small screens.
    setSelectedId(id)
    setDrawerOpen(false)
  }
  return (
    <div className={`dash view-fade-in${collapsed ? ' dash-collapsed' : ''}`}>
      {drawerOpen && <div className="dash-scrim" onClick={() => setDrawerOpen(false)} />}
      <aside className={`dash-sidebar${drawerOpen ? ' dash-sidebar-open' : ''}`} aria-label="New improvement and task history">
        <div className="dash-brand">
          <img src="/favicon-64.png" alt="" width="32" height="32" />
          <span>Agent Swarm</span>
          <button type="button" className="neu-pressable dash-drawer-close" onClick={() => setDrawerOpen(false)} aria-label="Close sidebar">✕</button>
        </div>
        <TaskForm onCreated={(task) => { setTasks((prev) => [task, ...prev]); selectTask(task.id) }} />
        <TaskHistorySidebar
          tasks={tasks}
          selectedId={selectedId}
          onSelect={selectTask}
          search={search}
          onSearchChange={setSearch}
          filter={filter}
          onFilterChange={setFilter}
          onTaskUpdated={handleTaskUpdated}
          onTaskDeleted={handleTaskDeleted}
        />
      </aside>
      <div className="dash-main">
        <header className="app-header">
          <button
            type="button"
            className="neu-flat neu-pressable dash-sidebar-toggle"
            onClick={toggleSidebar}
            aria-label={collapsed ? 'Show sidebar' : 'Toggle sidebar'}
            title={collapsed ? 'Show sidebar' : 'Hide sidebar'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
              <path d="M9.5 4.5v15" />
            </svg>
          </button>
          <Link to="/" className="neu-flat neu-pressable" style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}>
            ← Home
          </Link>
          <div style={{ flex: 1 }} />
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <UserMenu />
        </header>
        <main className="dash-content">
          <AgentTrace taskId={selectedId} theme={theme} onTaskChanged={handleDetailLoaded} />
        </main>
      </div>
    </div>
  )
}
