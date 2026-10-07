/**
 * The GraphRec logo and the decorative user–item graph. Shared by the console
 * shells, the auth showcase and the public marketing site so the brand exists once.
 */
export function BrandMark() {
  return <svg className="brand-mark" aria-hidden="true" viewBox="0 0 32 32" width="26" height="26">
    <rect width="32" height="32" rx="8" fill="var(--color-ink)" />
    <g stroke="var(--color-on-ink)" strokeWidth="1.6" opacity=".55"><path d="M10 11l12 -1M10 11l5 11M22 10l-7 12M22 10l2 9" /></g>
    <circle cx="10" cy="11" r="3" fill="var(--color-on-ink)" /><circle cx="22" cy="10" r="2.4" fill="var(--color-on-ink)" />
    <circle cx="15" cy="22" r="3" fill="var(--color-accent)" /><circle cx="24" cy="19" r="2" fill="var(--color-on-ink)" />
  </svg>;
}

type GraphNode = [x: number, y: number, r: number, hot: boolean];
const NODES: GraphNode[] = [
  [60, 70, 7, false], [170, 40, 5, false], [260, 95, 8, true], [120, 150, 6, false], [215, 185, 5, false],
  [320, 175, 6, false], [70, 235, 5, false], [175, 265, 9, true], [295, 270, 5, false], [345, 60, 4, false],
];
const EDGES: [number, number][] = [[0,1],[0,3],[1,2],[2,3],[2,5],[2,9],[3,4],[3,6],[4,7],[5,8],[6,7],[7,8],[4,5],[1,9]];
/** A shopper's path through the graph: shopper (7) → items (4, 3) → recommended item (2). */
const TRAIL = [7, 4, 3, 2];

/**
 * Decorative user–item graph (styled by `.auth-graph` in console.css). `trail`
 * overlays the highlighted path; the marketing hero draws it in with CSS.
 */
export function GraphIllustration({ trail = false, className }: { trail?: boolean; className?: string }) {
  return <svg className={`auth-graph${className ? ` ${className}` : ""}`} aria-hidden="true" focusable="false" viewBox="0 0 400 310" preserveAspectRatio="xMidYMid meet">
    {EDGES.map(([a, b], i) => <line key={i} x1={NODES[a][0]} y1={NODES[a][1]} x2={NODES[b][0]} y2={NODES[b][1]} className={NODES[a][3] && NODES[b][3] ? "e hot" : NODES[a][3] || NODES[b][3] ? "e warm" : "e"} />)}
    {trail ? <polyline className="trail" pathLength={1} points={TRAIL.map(i => `${NODES[i][0]},${NODES[i][1]}`).join(" ")} /> : null}
    {NODES.map(([x, y, r, hot], i) => <g key={i}>{hot ? <circle cx={x} cy={y} r={r + 7} className="halo" /> : null}<circle cx={x} cy={y} r={r} className={hot ? "n hot" : "n"} /></g>)}
  </svg>;
}
