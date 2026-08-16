import InfoTooltip from "./InfoTooltip.jsx";

// small dependency-free inline-SVG line chart - this frontend doesn't pull
// in a charting library anywhere else, so the metopic gradient/curvature/
// deviation profiles (App.jsx's Analysis panel) get the same treatment.
//
// referenceY (optional) overlays a second, dashed line on the same x/y
// scale - the metopic panels use this for the "ideal (parabola)" curve
// (see App.jsx's idealMetopicProfiles), the same reference line the PDF
// report already draws (see api/results_bundle.py's _draw_metopic), so a
// patient's line pulling away from the dashed one is visible directly on
// the chart instead of only readable from the raw numbers.
//
// bands (optional) shades vertical regions of the x-domain - the metopic
// panels use this for the central-ridge/left-temple/right-temple windows
// (metopic.central_window etc.) the numbers in the table above are actually
// computed from, so it's visible which part of the curve each number came
// from, and - just as usefully - which parts (the plain unshaded stretches
// near the very edges) aren't part of any window at all.
export default function ProfileChart({
  title,
  explainer,
  x,
  y,
  referenceY,
  referenceLabel,
  bands,
  color = "var(--primary)",
  zeroLine = false,
  height = 90,
}) {
  if (!x || !y || x.length === 0 || y.length === 0) return null;
  const hasReference = referenceY && referenceY.length === y.length;

  const width = 260;
  const padding = 6;
  const xMin = Math.min(...x);
  const xMax = Math.max(...x);
  const yValues = hasReference ? [...y, ...referenceY] : y;
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const toSvgX = (v) => padding + ((v - xMin) / xRange) * (width - 2 * padding);
  const toSvgY = (v) => height - padding - ((v - yMin) / yRange) * (height - 2 * padding);
  const points = x.map((xv, i) => `${toSvgX(xv)},${toSvgY(y[i])}`).join(" ");
  const referencePoints = hasReference ? x.map((xv, i) => `${toSvgX(xv)},${toSvgY(referenceY[i])}`).join(" ") : null;
  const zeroY = zeroLine && yMin <= 0 && yMax >= 0 ? toSvgY(0) : null;

  return (
    <div className="profile-chart">
      <p className="profile-chart-title">
        {title}
        <InfoTooltip text={explainer} />
      </p>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
        {bands?.map((band, i) => (
          <rect
            key={i}
            x={toSvgX(Math.max(band.x0, xMin))}
            y={0}
            width={Math.max(0, toSvgX(Math.min(band.x1, xMax)) - toSvgX(Math.max(band.x0, xMin)))}
            height={height}
            fill={band.color}
            opacity="0.12"
          />
        ))}
        {zeroY !== null && (
          <line x1={padding} y1={zeroY} x2={width - padding} y2={zeroY} stroke="var(--border)" strokeDasharray="3,2" />
        )}
        {referencePoints !== null && (
          <polyline points={referencePoints} fill="none" stroke={color} strokeWidth="1.2" strokeDasharray="4,3" opacity="0.55" />
        )}
        <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
      {hasReference && <p className="profile-chart-legend">— patient &nbsp;&nbsp; ‑ ‑ {referenceLabel || "ideal (parabola)"}</p>}
    </div>
  );
}
