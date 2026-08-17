// dependency-free inline-SVG histogram - same viewBox-based, CSS-var-colored
// style as components/ProfileChart.jsx (this frontend doesn't pull in a
// charting library anywhere, see that file's own comment for why).
export default function Histogram({ bins, color = "var(--primary)", height = 160 }) {
  if (!bins || bins.length === 0) return <p className="hint">Not enough numeric data to plot.</p>;

  const width = 420;
  const padding = 28;
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const plotWidth = width - 2 * padding;
  const plotHeight = height - 2 * padding;
  const barWidth = plotWidth / bins.length;

  const toX = (i) => padding + i * barWidth;
  const toBarHeight = (count) => (count / maxCount) * plotHeight;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--border)" />
      {bins.map((b, i) => {
        const barHeight = toBarHeight(b.count);
        return (
          <g key={i}>
            <rect
              x={toX(i) + 1}
              y={height - padding - barHeight}
              width={Math.max(0, barWidth - 2)}
              height={barHeight}
              fill={color}
              opacity="0.75"
            />
            <title>{`${b.x0.toFixed(2)} – ${b.x1.toFixed(2)}: ${b.count}`}</title>
          </g>
        );
      })}
      <text x={padding} y={height - 8} fontSize="9" fill="var(--text-muted)">
        {bins[0].x0.toFixed(1)}
      </text>
      <text x={width - padding} y={height - 8} fontSize="9" fill="var(--text-muted)" textAnchor="end">
        {bins[bins.length - 1].x1.toFixed(1)}
      </text>
      <text x={padding} y={12} fontSize="9" fill="var(--text-muted)">
        n = {bins.reduce((sum, b) => sum + b.count, 0)}, max bin {maxCount}
      </text>
    </svg>
  );
}
