import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function initials(user) {
  const source = user.name || user.email
  return source.slice(0, 2).toUpperCase()
}

export default function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  if (!user) return null

  const handleLogout = async () => {
    setOpen(false)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        className="neu-flat neu-pressable"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px 6px 6px', minHeight: 44 }}
      >
        <Avatar user={user} />
        <span className="user-menu-name" style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {user.name || user.email}
        </span>
      </button>

      {open && (
        <div
          className="neu-raised anim-fade-up"
          style={{ position: 'absolute', right: 0, top: 'calc(100% + 8px)', width: 220, padding: 12, zIndex: 20 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 6px 12px', borderBottom: '1px solid var(--shadow-dark)', marginBottom: 8 }}>
            <Avatar user={user} size={36} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.name || 'Account'}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email}</div>
            </div>
          </div>
          <button
            type="button"
            className="neu-pressable"
            onClick={handleLogout}
            style={{ width: '100%', textAlign: 'left', padding: '10px 8px', background: 'transparent', color: 'var(--danger)', minHeight: 44 }}
          >
            Logout
          </button>
        </div>
      )}
    </div>
  )
}

function Avatar({ user, size = 28 }) {
  if (user.avatar_url) {
    return <img src={user.avatar_url} alt="" width={size} height={size} style={{ borderRadius: '50%', flexShrink: 0 }} />
  }
  return (
    <span
      className="neu-inset"
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: size * 0.4,
        fontWeight: 700,
        color: 'var(--accent)',
        flexShrink: 0,
      }}
    >
      {initials(user)}
    </span>
  )
}
