// distinct, readable-on-dark colors for up to 8 stratify groups - cycles if
// there are more (no attempt at a "nice" categorical palette beyond that,
// this cohort workspace isn't trying to be a full charting library).
const PALETTE = ["#2f6fed", "#d1453d", "#178c83", "#e0a52c", "#7c5ce7", "#22a6a1", "#f28c45", "#8b5cf6"];

// dependency-free inline-SVG scatter plot - points is [{x, y, group}], group
// optional (falls back to a single un-colored series when the caller didn't
// pick a stratify column).
//
// sized via CSS (width:100% up to a max-width, height auto from
// aspect-ratio - see the .cohort-ws-chart rule) rather than a fixed SVG
// height attribute: with a fixed height and preserveAspectRatio="meet", a
// container wider than the viewBox's own aspect ratio (the usual case in
// this workspace's wide Plots panel) has nowhere to grow INTO - "meet"
// still only scales up to whichever of width/height is the tighter
// constraint, so the whole chart rendered at its native ~420x260 size,
// centered in a lot of unused empty space either side. matching the
// container's aspect ratio via CSS instead means there's no unequal
// constraint left to bind on, so it actually fills the space.
export default function ScatterPlot({ points, xLabel, yLabel }) {
  if (!points || points.length === 0) return <p className="hint">Not enough numeric data to plot.</p>;

  const width = 720;
  const height = 420;
  const padding = 56;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const toX = (v) => padding + ((v - xMin) / xRange) * (width - 2 * padding);
  const toY = (v) => height - padding - ((v - yMin) / yRange) * (height - 2 * padding);

  const groups = [...new Set(points.map((p) => p.group).filter((g) => g !== undefined))];
  const colorFor = (group) => (group === undefined ? "var(--primary)" : PALETTE[groups.indexOf(group) % PALETTE.length]);

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="cohort-ws-chart"
        style={{ aspectRatio: `${width} / ${height}` }}
        preserveAspectRatio="xMidYMid meet"
      >
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--border)" />
        <line x1={padding} y1={padding - 10} x2={padding} y2={height - padding} stroke="var(--border)" />
        {points.map((p, i) => (
          <circle key={i} cx={toX(p.x)} cy={toY(p.y)} r="4" fill={colorFor(p.group)} opacity="0.75">
            <title>{`${p.x}, ${p.y}${p.group !== undefined ? ` (${p.group})` : ""}`}</title>
          </circle>
        ))}
        <text x={width / 2} y={height - 12} fontSize="13" fill="var(--text-muted)" textAnchor="middle">{xLabel}</text>
        <text x={16} y={padding - 16} fontSize="13" fill="var(--text-muted)">{yLabel}</text>
      </svg>
      {groups.length > 0 && (
        <div className="cohort-ws-legend">
          {groups.map((g) => (
            <span key={g} className="cohort-ws-legend-item">
              <span className="cohort-ws-legend-swatch" style={{ background: colorFor(g) }} />
              {g}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
