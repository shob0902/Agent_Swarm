import { useEffect, useState } from 'react'
import './App.css'
import LoadingScreen from './components/LoadingScreen'
import LandingPage from './components/LandingPage'
import TaskForm from './components/TaskForm'
import TaskList from './components/TaskList'
import AgentTrace from './components/AgentTrace'
import { listTasks } from './api/client'

const THEME_KEY = 'agent-swarm-theme'
const TASK_LIST_POLL_MS = 3000

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'light')
  const [view, setView] = useState('loading') // 'loading' | 'landing' | 'dashboard'
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (view !== 'dashboard') return // no need to poll while the landing page is showing

    const fetchTasks = async () => {
      try {
        const data = await listTasks()
        const results = data.results ?? data // handle paginated or plain-array responses
        setTasks(results)
      } catch {
        // transient poll failure -- next tick retries
      }
    }
    fetchTasks()
    const interval = setInterval(fetchTasks, TASK_LIST_POLL_MS)
    return () => clearInterval(interval)
  }, [view])

  const toggleTheme = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))

  if (view === 'loading') {
    return <LoadingScreen onDone={() => setView('landing')} />
  }

  if (view === 'landing') {
    return <LandingPage theme={theme} onToggleTheme={toggleTheme} onEnter={() => setView('dashboard')} />
  }

  const selectedTask = tasks.find((t) => t.id === selectedId)

  return (
    <div className="app-shell view-fade-in">
      <header className="app-header">
        <button
          className="neu-flat neu-pressable"
          onClick={() => setView('landing')}
          style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}
        >
          ← Home
        </button>
        <button
          className="neu-flat neu-pressable"
          onClick={toggleTheme}
          style={{ padding: '8px 16px', color: 'var(--text-secondary)' }}
        >
          {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
        </button>
      </header>

      <main className="app-grid">
        <div className="app-column">
          <TaskForm onCreated={(task) => { setTasks((prev) => [task, ...prev]); setSelectedId(task.id) }} />
          <TaskList tasks={tasks} selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div className="app-column">
          <AgentTrace taskId={selectedId} taskStatus={selectedTask?.status} theme={theme} />
        </div>
      </main>
    </div>
  )
}
