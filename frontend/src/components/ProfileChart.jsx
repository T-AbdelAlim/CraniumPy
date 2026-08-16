// small dependency-free inline-SVG line chart - this frontend doesn't pull
// in a charting library anywhere else, so the metopic gradient/curvature/
// deviation profiles (App.jsx's Analysis panel) get the same treatment.
export default function ProfileChart({ title, x, y, color = "var(--primary)", zeroLine = false, height = 90 }) {
  if (!x || !y || x.length === 0 || y.length === 0) return null;

  const width = 260;
  const padding = 6;
  const xMin = Math.min(...x);
  const xMax = Math.max(...x);
  const yMin = Math.min(...y);
  const yMax = Math.max(...y);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const toSvgX = (v) => padding + ((v - xMin) / xRange) * (width - 2 * padding);
  const toSvgY = (v) => height - padding - ((v - yMin) / yRange) * (height - 2 * padding);
  const points = x.map((xv, i) => `${toSvgX(xv)},${toSvgY(y[i])}`).join(" ");
  const zeroY = zeroLine && yMin <= 0 && yMax >= 0 ? toSvgY(0) : null;

  return (
    <div className="profile-chart">
      <p className="profile-chart-title">{title}</p>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
        {zeroY !== null && (
          <line x1={padding} y1={zeroY} x2={width - padding} y2={zeroY} stroke="var(--border)" strokeDasharray="3,2" />
        )}
        <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
    </div>
  );
}
