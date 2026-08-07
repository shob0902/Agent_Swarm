import { useState } from 'react'
import * as ReactDiffViewerModule from 'react-diff-viewer-continued'

// This package ships CJS without an `__esModule` marker. Vite pre-bundles it
// by wrapping the whole `module.exports` (itself `{ LineNumberPrefix,
// DiffMethod, default: <Component> }`) as the single ESM default export --
// so a plain `import ReactDiffViewer from '...'` (or even `.default` once)
// resolves to that wrapper object, not the component, and React throws
// "Element type is invalid". Unwrap up to two levels deep, whichever
// actually lands on a function, so this holds regardless of how a given
// bundler's CJS interop happens to shake out.
const ReactDiffViewer =
  ReactDiffViewerModule.default?.default ?? ReactDiffViewerModule.default ?? ReactDiffViewerModule

// Renders the Coder agent's per-file rewrites as old/new diffs.
// fileDiffs: [{ path, old_content, new_content }]
export default function DiffViewer({ fileDiffs, theme = 'light' }) {
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
