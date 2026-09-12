// Shows the Coder agent's file rewrites as before/after diffs, one tab per file.
import { useState } from 'react'
import * as ReactDiffViewerModule from 'react-diff-viewer-continued'
const ReactDiffViewer =
  ReactDiffViewerModule.default?.default ?? ReactDiffViewerModule.default ?? ReactDiffViewerModule
export default function DiffViewer({ fileDiffs, theme = 'light' }) {
  // Tracks which file tab is selected and renders that file's diff.
  const [activeIndex, setActiveIndex] = useState(0)
  if (!fileDiffs || fileDiffs.length === 0) {
    return <p style={{ color: 'var(--text-muted)' }}>No diff to show yet.</p>
  }
  const active = fileDiffs[activeIndex] ?? fileDiffs[0]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {fileDiffs.map((f, i) => (
          <button
            key={f.path}
            onClick={() => setActiveIndex(i)}
            className={i === activeIndex ? 'neu-inset neu-pressable' : 'neu-flat neu-pressable'}
            style={{ padding: '6px 12px', fontSize: 12, color: 'var(--text-primary)' }}
          >
            {f.path}
          </button>
        ))}
      </div>
      <div className="neu-inset" style={{ overflow: 'auto', borderRadius: 'var(--radius-md)' }}>
        <ReactDiffViewer
          oldValue={active.old_content || ''}
          newValue={active.new_content || ''}
          splitView={false}
          useDarkTheme={theme === 'dark'}
          leftTitle={active.old_content ? 'before' : '(new file)'}
          rightTitle="after"
        />
      </div>
    </div>
  )
}
