// dependency-free inline-SVG multi-series line chart - sibling to
// ProfileChart.jsx (this frontend doesn't pull in a charting library
// anywhere), just multiple colored series sharing one axis instead of one
// series plus a dashed reference line. built for the Longitudinal
// workspace's Trends tab (measurements over time), but generic - nothing
// here is longitudinal-specific.
//
// series: [{id, label, unit, color, points: [{x: index, y: number|null}]}]
// xLabels: category labels, one per x index (e.g. "Timepoint 0") - this is
// a categorical axis (evenly spaced ticks), not a real time scale, since a
// slot's own label is free text, not necessarily a parseable date.
//
// a null y breaks that series' line around it (drawn as two separate
// polyline segments) rather than interpolating across a timepoint that
// genuinely has no value for that metric - e.g. a metopic-only field on a
// cranium-target slot, or a slot that hasn't finished measuring yet.
export default function TrendsChart({ series, xLabels, height = 320 }) {
  const hasAnyPoint = series.some((s) => s.points.some((p) => p.y !== null && p.y !== undefined));
  if (!hasAnyPoint) return <p className="hint">No data yet for the selected measurements.</p>;

  const width = 760;
  const padding = { top: 16, right: 16, bottom: 36, left: 52 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const xCount = xLabels.length;
  const xMax = Math.max(1, xCount - 1);
  const allY = series.flatMap((s) => s.points.map((p) => p.y)).filter((y) => y !== null && y !== undefined);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const yPad = (yMax - yMin) * 0.1 || Math.abs(yMax) * 0.1 || 1;
  const yLo = yMin - yPad;
  const yHi = yMax + yPad;
  const yRange = yHi - yLo || 1;

  const toSvgX = (i) => padding.left + (i / xMax) * plotW;
  const toSvgY = (v) => padding.top + plotH - ((v - yLo) / yRange) * plotH;

  // contiguous runs of non-null points, per series - each run becomes its
  // own <polyline>, so a gap (a timepoint with no value for this metric)
  // shows as a real break instead of a straight line jumping over it.
  function segments(points) {
    const runs = [];
    let current = [];
    for (const p of points) {
      if (p.y === null || p.y === undefined) {
        if (current.length) runs.push(current);
        current = [];
      } else {
        current.push(p);
      }
    }
    if (current.length) runs.push(current);
    return runs;
  }

  const yTicks = 5;
  const tickValues = Array.from({ length: yTicks + 1 }, (_, i) => yLo + (i / yTicks) * yRange);

  return (
    <div className="trends-chart">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="xMidYMid meet">
        {tickValues.map((v, i) => (
          <g key={i}>
            <line x1={padding.left} y1={toSvgY(v)} x2={width - padding.right} y2={toSvgY(v)} stroke="var(--border)" strokeWidth="1" opacity="0.5" />
            <text x={padding.left - 8} y={toSvgY(v)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="var(--text-muted)">
              {v.toFixed(Math.abs(v) < 10 ? 2 : 1)}
            </text>
          </g>
        ))}

        {xLabels.map((label, i) => (
          <text key={i} x={toSvgX(i)} y={height - padding.bottom + 16} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
            {label}
          </text>
        ))}

        {series.map((s) =>
          segments(s.points).map((run, i) => (
            <polyline
              key={`${s.id}-${i}`}
              points={run.map((p) => `${toSvgX(p.x)},${toSvgY(p.y)}`).join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth="2"
            />
          ))
        )}
        {series.map((s) =>
          s.points
            .filter((p) => p.y !== null && p.y !== undefined)
            .map((p) => (
              <circle key={`${s.id}-${p.x}`} cx={toSvgX(p.x)} cy={toSvgY(p.y)} r="3.5" fill={s.color}>
                <title>
                  {xLabels[p.x]}: {s.label} = {p.y.toFixed(2)} {s.unit}
                </title>
              </circle>
            ))
        )}
      </svg>
      <div className="trends-chart-legend">
        {series.map((s) => (
          <span key={s.id} className="trends-chart-legend-item">
            <span className="viewer-legend-swatch" style={{ background: s.color, display: "inline-block" }} />
            {s.label}
            {s.unit ? ` (${s.unit})` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
