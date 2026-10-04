// n8n-style workflow canvas: trigger -> six square stage nodes (label underneath), attached model/tool
// sub-nodes, live connectors with data labels, and the two retry loops back into the Coder.
import { useEffect, useRef, useState } from 'react'
import PipelineIcon from './PipelineIcons'
import { STAGES, connectorLabels, loopUsage, stageState, triggerState } from './pipelineModel'
import './PipelineGraph.css'
// Canvas geometry (px). Nodes are HTML buttons placed over an SVG layer that draws the connectors.
const NODE = 56
const STEP = 106
const STAGE_X0 = 118
const ROW_Y = 92
const TRIGGER_X = 14
const LABEL_W = 104
const PORT_Y = ROW_Y + NODE + 46
const SUB_Y = 254
const SUB_R = 18
// Wide enough for the last node's label, which is wider than the node itself.
const CANVAS_W = STAGE_X0 + STEP * (STAGES.length - 1) + NODE / 2 + LABEL_W / 2 + 8
const CANVAS_H = 340 // includes a bottom strip for the zoom toolbar
const MID_Y = ROW_Y + NODE / 2
const stageX = (i) => STAGE_X0 + i * STEP
const centreX = (i) => stageX(i) + NODE / 2
// Short captions under each node; the logs panel has the long form.
const DONE_CAPTION = { analyzer: 'Analyzed', planner: 'Plan ready', coder: 'Code written', tester: 'Passed', reviewer: 'Approved', github: 'PR opened' }
const CAPTION = { pending: 'Waiting', running: 'Running…', retrying: 'Retrying', failed: 'Failed', skipped: 'Skipped' }
const BADGE_ICON = { success: 'check', failed: 'cross', retrying: 'retry', skipped: 'skip' }
function edgeState(from, to) {
  // Connector look: data flowing into a running node, a completed path, or idle.
  if (from === 'success' && (to === 'running' || to === 'retrying')) return 'flowing'
  if (from === 'success' && to !== 'pending') return 'done'
  if (from === 'success') return 'ready'
  return 'idle'
}
function shorten(text, max = 9) {
  // Keeps connector labels inside the gap between nodes; the full text is in the tooltip.
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}
const MIN_ZOOM = 0.5
const MAX_ZOOM = 2
const ZOOM_STEP = 1.2
// "Fit" never shrinks below this, so labels stay readable on phones (the canvas pans instead).
const MIN_FIT_ZOOM = 0.62
const MAX_FIT_ZOOM = 1.3
const clampZoom = (z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))
export default function PipelineGraph({ task, grouped, selected, onSelect }) {
  // Draws the canvas with n8n-like zoom/pan controls and reports node clicks.
  const scrollRef = useRef(null)
  const dragRef = useRef(null)
  const [zoomMode, setZoomMode] = useState('fit')
  const [manualZoom, setManualZoom] = useState(1)
  const [fitZoom, setFitZoom] = useState(1)
  const zoom = zoomMode === 'fit' ? fitZoom : manualZoom
  const states = Object.fromEntries(STAGES.map((s) => [s.key, stageState(task, grouped, s.key)]))
  const trigger = triggerState(task)
  const labels = { ...connectorLabels(task, grouped), trigger: 'request' }
  const loops = loopUsage(task, grouped)
  useEffect(() => {
    // Recomputes the "fit" zoom whenever the card changes width.
    const el = scrollRef.current
    if (!el) return undefined
    const measure = () => setFitZoom(Math.min(MAX_FIT_ZOOM, Math.max(MIN_FIT_ZOOM, (el.clientWidth - 2) / CANVAS_W)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    // Ctrl/Cmd + wheel zooms (plain wheel keeps scrolling the page). Needs a non-passive native listener.
    const el = scrollRef.current
    if (!el) return undefined
    const onWheel = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      setZoomMode('manual')
      setManualZoom((z) => clampZoom((zoomMode === 'fit' ? fitZoom : z) * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomMode, fitZoom])
  useEffect(() => {
    // Keeps the selected node in view when the canvas is wider than its card.
    const el = scrollRef.current
    if (!el || el.scrollWidth <= el.clientWidth) return
    const i = STAGES.findIndex((s) => s.key === selected)
    const centre = (i >= 0 ? centreX(i) : TRIGGER_X + NODE / 2) * zoom
    el.scrollTo({ left: Math.max(0, centre - el.clientWidth / 2), behavior: 'smooth' })
  }, [selected, zoom])
  const zoomBy = (factor) => {
    // Zoom buttons: switch to manual zoom, starting from whatever is currently shown.
    setZoomMode('manual')
    setManualZoom(clampZoom(zoom * factor))
  }
  const onPointerDown = (e) => {
    // Drag empty canvas to pan, like n8n; clicks on nodes are left alone.
    const el = scrollRef.current
    const scrollable = el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight
    if (e.button !== 0 || e.target.closest('button') || !scrollable) return
    dragRef.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop }
    el.setPointerCapture(e.pointerId)
    el.classList.add('flow-dragging')
  }
  const onPointerMove = (e) => {
    // Moves the view while dragging.
    const drag = dragRef.current
    if (!drag) return
    const el = scrollRef.current
    el.scrollLeft = drag.left - (e.clientX - drag.x)
    el.scrollTop = drag.top - (e.clientY - drag.y)
  }
  const endDrag = (e) => {
    // Stops panning.
    if (!dragRef.current) return
    dragRef.current = null
    scrollRef.current.releasePointerCapture?.(e.pointerId)
    scrollRef.current.classList.remove('flow-dragging')
  }
  const chain = [{ key: 'trigger', state: trigger, right: TRIGGER_X + NODE }, ...STAGES.map((s, i) => ({ key: s.key, state: states[s.key], right: stageX(i) + NODE }))]
  const coderX = centreX(2)
  const testerX = centreX(3)
  const reviewerX = centreX(4)
  return (
    <div className="flow-viewport">
    <div
      className="flow-scroll"
      ref={scrollRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <div className="flow-sizer" style={{ width: CANVAS_W * zoom, height: CANVAS_H * zoom }}>
      <div className="flow-canvas" style={{ width: CANVAS_W, height: CANVAS_H, transform: `scale(${zoom})` }} role="group" aria-label="Agent pipeline">
        <svg className="flow-edges" width={CANVAS_W} height={CANVAS_H} aria-hidden="true">
          <defs>
            {['idle', 'ready', 'done', 'flowing', 'loop', 'loop-used'].map((kind) => (
              <marker key={kind} id={`arrow-${kind}`} viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 1 L9 5 L0 9 z" className={`flow-arrow flow-arrow-${kind}`} />
              </marker>
            ))}
          </defs>
          {/* Main connectors with their data labels */}
          {chain.slice(0, -1).map((from, i) => {
            const to = chain[i + 1]
            const kind = edgeState(from.state, to.state)
            const x1 = from.right + 2
            const x2 = stageX(i) - 3
            const label = labels[from.key]
            return (
              <g key={`edge-${from.key}`}>
                <path d={`M${x1} ${MID_Y} L${x2} ${MID_Y}`} className={`flow-edge flow-edge-${kind}`} markerEnd={`url(#arrow-${kind})`} />
                {label && kind !== 'idle' && (
                  <text x={(x1 + x2) / 2} y={MID_Y - 8} className="flow-edge-label" textAnchor="middle">
                    <title>{label}</title>
                    {shorten(label)}
                  </text>
                )}
              </g>
            )
          })}
          {/* Retry loops back into the Coder */}
          <path
            d={`M${testerX - 10} ${ROW_Y - 2} C ${testerX - 10} ${ROW_Y - 40}, ${coderX + 10} ${ROW_Y - 40}, ${coderX + 10} ${ROW_Y - 4}`}
            className={`flow-loop${loops.testFixes ? ' flow-loop-used' : ''}`}
            markerEnd={`url(#arrow-${loops.testFixes ? 'loop-used' : 'loop'})`}
          />
          <text x={(testerX + coderX) / 2} y={ROW_Y - 36} textAnchor="middle" className={`flow-loop-label${loops.testFixes ? ' flow-loop-label-used' : ''}`}>
            {loops.testFixes ? `fix tests ×${loops.testFixes}` : 'on test failure'}
          </text>
          <path
            d={`M${reviewerX} ${ROW_Y - 2} C ${reviewerX} ${ROW_Y - 84}, ${coderX - 10} ${ROW_Y - 84}, ${coderX - 10} ${ROW_Y - 4}`}
            className={`flow-loop${loops.reviewCycles ? ' flow-loop-used' : ''}`}
            markerEnd={`url(#arrow-${loops.reviewCycles ? 'loop-used' : 'loop'})`}
          />
          <text x={(reviewerX + coderX) / 2} y={ROW_Y - 68} textAnchor="middle" className={`flow-loop-label${loops.reviewCycles ? ' flow-loop-label-used' : ''}`}>
            {loops.reviewCycles ? `changes requested ×${loops.reviewCycles}` : 'on review rejection'}
          </text>
          {/* Attached resources: dashed links from each stage's bottom port */}
          {STAGES.map((s, i) => {
            const cx = centreX(i)
            const used = states[s.key] !== 'pending'
            return (
              <g key={`sub-${s.key}`}>
                <path d={`M${cx} ${PORT_Y + 4} L${cx} ${SUB_Y - SUB_R - 2}`} className={`flow-sub-link${used ? ' flow-sub-link-used' : ''}`} />
                <rect x={cx - 4} y={PORT_Y - 4} width="8" height="8" transform={`rotate(45 ${cx} ${PORT_Y})`} className="flow-port" />
                <text x={cx + 8} y={PORT_Y + 18} className="flow-sub-kind">{s.resource.kind}</text>
              </g>
            )
          })}
        </svg>
        {/* Trigger node */}
        <button
          type="button"
          className={`flow-trigger flow-state-${trigger}${selected === 'trigger' ? ' flow-selected' : ''}`}
          style={{ left: TRIGGER_X, top: ROW_Y, width: NODE, height: NODE }}
          onClick={() => onSelect('trigger')}
          aria-label={`Task trigger, ${trigger === 'running' ? 'waiting for the runner' : 'started'}`}
          aria-pressed={selected === 'trigger'}
        >
          <PipelineIcon name="trigger" size={24} />
        </button>
        <div className="flow-label" style={{ left: TRIGGER_X + NODE / 2 - LABEL_W / 2, top: ROW_Y + NODE + 8, width: LABEL_W }}>
          <strong>Task #{task.id}</strong>
          <span>{trigger === 'running' ? 'Queued' : 'Started'}</span>
        </div>
        {/* Stage nodes: icon square, status badge, attempt counter, label underneath */}
        {STAGES.map((s, i) => {
          const state = states[s.key]
          const attempts = grouped[s.key].length
          const caption = state === 'success' ? DONE_CAPTION[s.key] : CAPTION[state]
          return (
            <div key={s.key}>
              <button
                type="button"
                className={`flow-node flow-state-${state}${selected === s.key ? ' flow-selected' : ''}`}
                style={{ left: stageX(i), top: ROW_Y, width: NODE, height: NODE }}
                onClick={() => onSelect(s.key)}
                aria-label={`${s.name}: ${state === 'success' ? s.done : caption}${attempts > 1 ? `, ${attempts} attempts` : ''}`}
                aria-pressed={selected === s.key}
              >
                <PipelineIcon name={s.key} size={26} />
                {attempts > 1 && <span className="flow-node-count">×{attempts}</span>}
                <span className="flow-node-badge" aria-hidden="true">
                  {state === 'running' ? <span className="flow-spinner" /> : <PipelineIcon name={BADGE_ICON[state]} size={11} strokeWidth={3} />}
                </span>
              </button>
              <div className={`flow-label flow-label-${state}`} style={{ left: centreX(i) - LABEL_W / 2, top: ROW_Y + NODE + 8, width: LABEL_W }}>
                <strong>{s.name}</strong>
                <span>{caption}</span>
              </div>
            </div>
          )
        })}
        {/* Sub-nodes (model / sandbox / tool) */}
        {STAGES.map((s, i) => {
          const used = states[s.key] !== 'pending'
          return (
            <button
              key={`res-${s.key}`}
              type="button"
              tabIndex={-1}
              className={`flow-sub${used ? ' flow-sub-used' : ''}${states[s.key] === 'running' ? ' flow-sub-busy' : ''}`}
              style={{ left: centreX(i) - SUB_R, top: SUB_Y - SUB_R, width: SUB_R * 2, height: SUB_R * 2 }}
              onClick={() => onSelect(s.key)}
              aria-hidden="true"
              title={s.resource.name}
            >
              <PipelineIcon name={s.resource.icon} size={16} />
              <span className="flow-sub-name">{s.resource.name}</span>
            </button>
          )
        })}
      </div>
      </div>
    </div>
      <div className="flow-zoom" role="toolbar" aria-label="Canvas zoom">
        <button type="button" onClick={() => setZoomMode('fit')} className={zoomMode === 'fit' ? 'flow-zoom-active' : ''} title="Fit to width" aria-label="Fit to width" aria-pressed={zoomMode === 'fit'}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>
        </button>
        <button type="button" onClick={() => zoomBy(1 / ZOOM_STEP)} disabled={zoom <= MIN_ZOOM + 0.001} title="Zoom out (Ctrl + scroll)" aria-label="Zoom out">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M5 12h14" /></svg>
        </button>
        <button type="button" className="flow-zoom-level" onClick={() => { setZoomMode('manual'); setManualZoom(1) }} title="Reset to 100%" aria-label={`Zoom ${Math.round(zoom * 100)}%, reset to 100%`}>
          {Math.round(zoom * 100)}%
        </button>
        <button type="button" onClick={() => zoomBy(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM - 0.001} title="Zoom in (Ctrl + scroll)" aria-label="Zoom in">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M5 12h14M12 5v14" /></svg>
        </button>
      </div>
    </div>
  )
}
