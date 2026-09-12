// Intro splash that cycles the four agent names once, then fades out into the landing page.
import { useEffect, useState } from 'react'
import './LoadingScreen.css'
const AGENTS = ['Planner', 'Coder', 'Tester', 'Reviewer']
const DISPLAY_MS = 2300
const EXIT_MS = 500
export default function LoadingScreen({ onDone }) {
  // Steps through the agent names on a timer, then calls onDone once the fade-out finishes.
  const [activeIndex, setActiveIndex] = useState(0)
  const [exiting, setExiting] = useState(false)
  useEffect(() => {
    const stepMs = DISPLAY_MS / AGENTS.length
    const stepInterval = setInterval(() => {
      setActiveIndex((i) => (i + 1) % AGENTS.length)
    }, stepMs)
    const exitTimer = setTimeout(() => setExiting(true), DISPLAY_MS)
    const doneTimer = setTimeout(() => onDone(), DISPLAY_MS + EXIT_MS)
    return () => {
      clearInterval(stepInterval)
      clearTimeout(exitTimer)
      clearTimeout(doneTimer)
    }
  }, [onDone])
  return (
    <div className={`loading-screen${exiting ? ' loading-exit' : ''}`}>
      <div className="loading-orbit">
        <svg className="loading-rings" viewBox="0 0 200 200">
          <circle cx="100" cy="100" r="80" className="loading-ring loading-ring-1" />
          <circle cx="100" cy="100" r="64" className="loading-ring loading-ring-2" />
        </svg>
        {AGENTS.map((agent, i) => (
          <div key={agent} className={`loading-node loading-node-${i}${i === activeIndex ? ' loading-node-active' : ''}`}>
            <span className="loading-node-dot" />
            <span className="loading-node-label">{agent}</span>
          </div>
        ))}
        <div className="loading-core" />
      </div>
      <p className="loading-status">Spinning up the agent swarm…</p>
      <div className="loading-bar">
        <div className="loading-bar-fill" />
      </div>
    </div>
  )
}
