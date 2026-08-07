import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './App.css'
import { AuthProvider } from './context/AuthContext'
import RequireAuth from './components/RequireAuth'
import LoadingScreen from './components/LoadingScreen'
import LandingPage from './components/LandingPage'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import AuthCallbackPage from './pages/AuthCallbackPage'
import DashboardPage from './pages/DashboardPage'

const THEME_KEY = 'agent-swarm-theme'

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'light')
  // One-time intro flourish gating the whole app on first mount, regardless
  // of which route the user lands on (deep link, refresh, etc).
  const [introDone, setIntroDone] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const toggleTheme = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))

  if (!introDone) {
    return <LoadingScreen onDone={() => setIntroDone(true)} />
  }

  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage theme={theme} onToggleTheme={toggleTheme} />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/auth/callback/:provider" element={<AuthCallbackPage />} />
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardPage theme={theme} onToggleTheme={toggleTheme} />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
