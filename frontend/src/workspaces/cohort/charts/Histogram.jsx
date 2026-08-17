// dependency-free inline-SVG histogram - same viewBox-based, CSS-var-colored
// style as components/ProfileChart.jsx (this frontend doesn't pull in a
// charting library anywhere, see that file's own comment for why).
//
// sized via CSS (see the .cohort-ws-chart rule, and ScatterPlot's own
// comment on why) rather than a fixed SVG height + preserveAspectRatio=
// "none" - "none" filled the full container width like this always should,
// but did it by stretching x and y independently by DIFFERENT factors
// (whatever the container's own width happened to be vs. a fixed height
// prop), which distorts every axis-aligned distance that isn't supposed to
// scale with it - most visibly the text, which comes out visibly squashed/
// stretched instead of reading as normal letterforms. matching the
// container's aspect ratio via CSS instead means the one scale factor left
// (uniform, via "meet") already fills the width on its own, with nothing
// left to stretch non-uniformly for.
export default function Histogram({ bins, color = "var(--primary)" }) {
  if (!bins || bins.length === 0) return <p className="hint">Not enough numeric data to plot.</p>;

  const width = 900;
  const height = 300;
  const padding = 50;
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const plotWidth = width - 2 * padding;
  const plotHeight = height - 2 * padding;
  const barWidth = plotWidth / bins.length;

  const toX = (i) => padding + i * barWidth;
  const toBarHeight = (count) => (count / maxCount) * plotHeight;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="cohort-ws-chart"
      style={{ aspectRatio: `${width} / ${height}` }}
      preserveAspectRatio="xMidYMid meet"
    >
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
      <text x={padding} y={height - 14} fontSize="13" fill="var(--text-muted)">
        {bins[0].x0.toFixed(1)}
      </text>
      <text x={width - padding} y={height - 14} fontSize="13" fill="var(--text-muted)" textAnchor="end">
        {bins[bins.length - 1].x1.toFixed(1)}
      </text>
      <text x={padding} y={18} fontSize="13" fill="var(--text-muted)">
        n = {bins.reduce((sum, b) => sum + b.count, 0)}, max bin {maxCount}
      </text>
    </svg>
  );
}
