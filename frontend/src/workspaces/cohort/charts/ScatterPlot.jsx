// distinct, readable-on-dark colors for up to 8 stratify groups - cycles if
// there are more (no attempt at a "nice" categorical palette beyond that,
// this cohort workspace isn't trying to be a full charting library).
const PALETTE = ["#2f6fed", "#d1453d", "#178c83", "#e0a52c", "#7c5ce7", "#22a6a1", "#f28c45", "#8b5cf6"];

// dependency-free inline-SVG scatter plot - points is [{x, y, group}], group
// optional (falls back to a single un-colored series when the caller didn't
// pick a stratify column).
export default function ScatterPlot({ points, xLabel, yLabel, height = 260 }) {
  if (!points || points.length === 0) return <p className="hint">Not enough numeric data to plot.</p>;

  const width = 420;
  const padding = 36;
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
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="xMidYMid meet">
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--border)" />
        <line x1={padding} y1={padding - 6} x2={padding} y2={height - padding} stroke="var(--border)" />
        {points.map((p, i) => (
          <circle key={i} cx={toX(p.x)} cy={toY(p.y)} r="3" fill={colorFor(p.group)} opacity="0.75">
            <title>{`${p.x}, ${p.y}${p.group !== undefined ? ` (${p.group})` : ""}`}</title>
          </circle>
        ))}
        <text x={width / 2} y={height - 6} fontSize="9" fill="var(--text-muted)" textAnchor="middle">{xLabel}</text>
        <text x={10} y={padding - 10} fontSize="9" fill="var(--text-muted)">{yLabel}</text>
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
