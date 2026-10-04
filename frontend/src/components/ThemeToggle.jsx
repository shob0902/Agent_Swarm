// Light/dark switch: an inset track with sun and moon icons and a raised knob that slides to the active theme.
import './ThemeToggle.css'
export default function ThemeToggle({ theme, onToggle }) {
  // Renders an accessible switch; "checked" means dark mode is on.
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className={`theme-toggle${isDark ? ' theme-toggle-dark' : ''}`}
      onClick={onToggle}
    >
      <span className="theme-toggle-knob" aria-hidden="true" />
      <span className="theme-toggle-icon theme-toggle-sun" aria-hidden="true">
        <SunIcon />
      </span>
      <span className="theme-toggle-icon theme-toggle-moon" aria-hidden="true">
        <MoonIcon />
      </span>
    </button>
  )
}
function SunIcon() {
  // Simple outlined sun, drawn in the current text colour.
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}
function MoonIcon() {
  // Simple outlined crescent moon, drawn in the current text colour.
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}
