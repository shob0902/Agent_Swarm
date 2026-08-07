import StatusBadge from './StatusBadge'

export default function TaskList({ tasks, selectedId, onSelect }) {
  return (
    <div className="neu-raised" style={{ padding: 20 }}>
      <h2 style={{ marginTop: 0 }}>Tasks</h2>
      {tasks.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No tasks yet — submit one above.</p>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {tasks.map((task, i) => (
          <button
            key={task.id}
            onClick={() => onSelect(task.id)}
            className={`anim-fade-up ${task.id === selectedId ? 'neu-inset neu-pressable' : 'neu-flat neu-pressable'}`}
            style={{
              textAlign: 'left',
              padding: '12px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
              animationDelay: `${Math.min(i, 8) * 0.05}s`,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-muted)' }}>#{task.id}</span>
              <StatusBadge status={task.status} />
            </div>
            <div style={{ color: 'var(--text-primary)', fontSize: 14 }}>{task.description}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{task.repo_path}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
