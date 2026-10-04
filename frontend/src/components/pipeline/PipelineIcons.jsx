// Outlined icons for the workflow canvas, drawn in the current text colour.
const PATHS = {
  trigger: 'M13 2 4 14h7l-1 8 9-12h-7z',
  analyzer: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.3 15.3 20 20',
  planner: 'M9 5h11M9 12h11M9 19h11M4.5 4.5h1v1h-1zM4.5 11.5h1v1h-1zM4.5 18.5h1v1h-1z',
  coder: 'M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15',
  tester: 'M9 3h6M10 3v6.2L4.6 18.4A1.7 1.7 0 0 0 6.1 21h11.8a1.7 1.7 0 0 0 1.5-2.6L14 9.2V3M7.2 15h9.6',
  reviewer: 'M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6zM8.8 12.2l2.2 2.2 4.4-4.6',
  github: 'M6.5 3.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM6.5 15.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM17.5 15.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM6.5 8.5v7M17.5 15.5V9a3 3 0 0 0-3-3H11M13 3.5 10.5 6 13 8.5',
  cpu: 'M8 4v2M12 4v2M16 4v2M8 18v2M12 18v2M16 18v2M4 8h2M4 12h2M4 16h2M18 8h2M18 12h2M18 16h2M7 6h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zM10 10h4v4h-4z',
  box: 'M12 3 4 7.5v9L12 21l8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
  branch: 'M6.5 3.5v11M6.5 14.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM17.5 4.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM17.5 9.5c0 4-4 4-11 5',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  cross: 'M6.5 6.5l11 11M17.5 6.5l-11 11',
  retry: 'M4.5 12a7.5 7.5 0 0 1 13-5.1M19.5 12a7.5 7.5 0 0 1-13 5.1M17.5 3.5v3.5H14M6.5 20.5V17H10',
  skip: 'M5 12h11M13 8l4 4-4 4M19 6v12',
}
export default function PipelineIcon({ name, size = 20, strokeWidth = 1.8 }) {
  // One icon; unknown names render nothing.
  const d = PATHS[name]
  if (!d) return null
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}
