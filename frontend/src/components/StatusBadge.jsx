// Small coloured status pill used by the task sidebar and the agent trace.
const COLOR_BY_STATUS = {
  pending: 'var(--text-muted)',
  planning: 'var(--info)',
  coding: 'var(--info)',
  testing: 'var(--info)',
  review: 'var(--info)',
  done: 'var(--success)',
  success: 'var(--success)',
  failed: 'var(--danger)',
  failure: 'var(--danger)',
}
export default function StatusBadge({ status }) {
  // Picks the colour for the given status and renders it as a dot plus label.
  const color = COLOR_BY_STATUS[status] || 'var(--text-muted)'
  return (
    <span
      className="neu-flat"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 12px',
        fontSize: 12,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: 0.4,
        color,
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
      {status}
    </span>
  )
}
