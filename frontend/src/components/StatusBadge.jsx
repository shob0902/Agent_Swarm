// Small coloured status pill used by the task sidebar, the pipeline panel and the agent trace.
const COLOR_BY_STATUS = {
  pending: 'var(--text-muted)',
  queued: 'var(--text-muted)',
  analyzing: 'var(--info)',
  planning: 'var(--info)',
  coding: 'var(--info)',
  testing: 'var(--info)',
  review: 'var(--info)',
  publishing: 'var(--info)',
  creating: 'var(--info)',
  done: 'var(--success)',
  success: 'var(--success)',
  passed: 'var(--success)',
  approved: 'var(--success)',
  open: 'var(--success)',
  merged: 'var(--success)',
  skipped: 'var(--warning)',
  closed: 'var(--warning)',
  failed: 'var(--danger)',
  failure: 'var(--danger)',
  rejected: 'var(--danger)',
}
export default function StatusBadge({ status, label }) {
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
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
      {label || status || 'not run'}
    </span>
  )
}
