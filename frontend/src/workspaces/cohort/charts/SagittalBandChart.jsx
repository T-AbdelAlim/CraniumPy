// dependency-free inline-SVG line+band chart for the mean sagittal midline
// profile (see craniumpy_core.cohort.sagittal_midline_band) - a solid mean
// line with a shaded +/-1 SD band around it, showing how much the group's
// own forehead-to-vertex depth varies at each height, not just its
// average. same viewBox-based, CSS-var-colored style as the other cohort
// charts (see BoxPlot.jsx/Histogram.jsx/ScatterPlot.jsx).
export default function SagittalBandChart({ y, meanZ, sdZ, color = "var(--primary)", height = 220 }) {
  if (!y || y.length === 0) return <p className="hint">Not enough data to plot.</p>;

  const width = 420;
  const padding = 36;
  const upperZ = meanZ.map((v, i) => v + sdZ[i]);
  const lowerZ = meanZ.map((v, i) => v - sdZ[i]);
  const yMin = Math.min(...y);
  const yMax = Math.max(...y);
  const zMin = Math.min(...lowerZ);
  const zMax = Math.max(...upperZ);
  const yRange = yMax - yMin || 1;
  const zRange = zMax - zMin || 1;

  const toX = (v) => padding + ((v - yMin) / yRange) * (width - 2 * padding);
  const toY = (v) => height - padding - ((v - zMin) / zRange) * (height - 2 * padding);

  const meanPoints = y.map((yv, i) => `${toX(yv)},${toY(meanZ[i])}`).join(" ");
  const bandPath =
    y.map((yv, i) => `${i === 0 ? "M" : "L"}${toX(yv)},${toY(upperZ[i])}`).join(" ") +
    " " +
    [...y].reverse().map((yv, i) => `L${toX(yv)},${toY(lowerZ[lowerZ.length - 1 - i])}`).join(" ") +
    " Z";

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="xMidYMid meet">
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--border)" />
      <line x1={padding} y1={padding - 6} x2={padding} y2={height - padding} stroke="var(--border)" />
      <path d={bandPath} fill={color} opacity="0.2" stroke="none" />
      <polyline points={meanPoints} fill="none" stroke={color} strokeWidth="1.8" />
      <text x={padding} y={height - 8} fontSize="9" fill="var(--text-muted)">
        sellion height +{yMin.toFixed(0)} mm
      </text>
      <text x={width - padding} y={height - 8} fontSize="9" fill="var(--text-muted)" textAnchor="end">
        +{yMax.toFixed(0)} mm (vertex)
      </text>
      <text x={4} y={toY(zMax) + 3} fontSize="9" fill="var(--text-muted)">{zMax.toFixed(0)}</text>
      <text x={4} y={toY(zMin) + 3} fontSize="9" fill="var(--text-muted)">{zMin.toFixed(0)}</text>
    </svg>
  );
}
