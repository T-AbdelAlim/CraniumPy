import { describe } from "../lib/stats.js";

// dependency-free inline-SVG box plot, one box per group - median line,
// Q1-Q3 box, whiskers to min/max (no separate outlier handling - a cohort
// this size doesn't need it, and a stray extreme value is exactly the kind
// of thing worth seeing on the chart rather than hidden as an "outlier").
export default function BoxPlot({ groups, color = "var(--primary)", height = 200 }) {
  const labels = Object.keys(groups).filter((label) => groups[label].length > 0);
  if (labels.length === 0) return <p className="hint">Not enough numeric data to plot.</p>;

  const padding = 32;
  // wide enough for the longest group label to sit in its own slot without
  // crowding its neighbor - a plain length*charWidth estimate (there's no
  // way to actually measure rendered text width ahead of laying out an SVG
  // like this), generous enough for this app's own sans-serif font at this
  // size. this is the fix for long category names like
  // "positional_plagiocephaly" overlapping their neighbor: widen the slot,
  // not shrink the font - shrinking would just delay the same problem for
  // the next-longest label a group or two later.
  const maxLabelChars = Math.max(...labels.map((label) => label.length));
  const slot = Math.max(90, maxLabelChars * 5.6 + 16);
  const width = 2 * padding + slot * labels.length;
  const stats = labels.map((label) => describe(groups[label]));
  const allValues = labels.flatMap((label) => groups[label]);
  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);
  const yRange = yMax - yMin || 1;
  const plotHeight = height - 2 * padding;
  const toY = (v) => height - padding - ((v - yMin) / yRange) * plotHeight;
  const boxWidth = Math.min(60, slot * 0.5);

  return (
    // an explicit pixel width (not "100%") plus a horizontal-scroll wrapper,
    // deliberately NOT this app's usual scale-to-container-width chart
    // pattern (see Histogram.jsx/ScatterPlot.jsx's own comments) - those
    // charts' content doesn't depend on how much horizontal room text needs,
    // this one's does. scaling the viewBox down to fit a narrow container
    // would shrink the label font right along with everything else; letting
    // it overflow into a scrollbar instead keeps the font at its authored
    // size no matter how many groups or how long their names are.
    <div className="cohort-ws-boxplot-scroll">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height}>
        <line x1={padding} y1={padding - 6} x2={padding} y2={height - padding} stroke="var(--border)" />
        <text x={4} y={toY(yMax) + 3} fontSize="9" fill="var(--text-muted)">{yMax.toFixed(1)}</text>
        <text x={4} y={toY(yMin) + 3} fontSize="9" fill="var(--text-muted)">{yMin.toFixed(1)}</text>
        {labels.map((label, i) => {
          const s = stats[i];
          const cx = padding + slot * (i + 0.5);
          return (
            <g key={label}>
              <line x1={cx} y1={toY(s.min)} x2={cx} y2={toY(s.max)} stroke={color} strokeWidth="1" />
              <rect
                x={cx - boxWidth / 2}
                y={toY(s.q3)}
                width={boxWidth}
                height={Math.max(1, toY(s.q1) - toY(s.q3))}
                fill={color}
                opacity="0.35"
                stroke={color}
              />
              <line x1={cx - boxWidth / 2} y1={toY(s.median)} x2={cx + boxWidth / 2} y2={toY(s.median)} stroke={color} strokeWidth="2" />
              <text x={cx} y={height - padding + 14} fontSize="9" fill="var(--text-secondary)" textAnchor="middle">
                {label}
              </text>
              <text x={cx} y={height - padding + 25} fontSize="8" fill="var(--text-muted)" textAnchor="middle">
                n={s.n}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
