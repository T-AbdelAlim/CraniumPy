import { useMemo, useState } from "react";
import { columnType, histogramBins, numericValues, toNumber } from "../lib/stats.js";
import ScatterPlot from "../charts/ScatterPlot.jsx";
import Histogram from "../charts/Histogram.jsx";

// freeform metric-vs-metric scatter (optionally colored by a categorical
// column) and a single-metric histogram - both dependency-free inline SVG
// (see charts/), matching the rest of this app's no-charting-library style.
export default function PlotsTab({ rows, columns }) {
  const types = useMemo(() => Object.fromEntries(columns.map((c) => [c, columnType(rows, c)])), [rows, columns]);
  const numericColumns = columns.filter((c) => types[c] === "numeric");
  const categoricalColumns = columns.filter((c) => types[c] === "categorical");

  const [xColumn, setXColumn] = useState(numericColumns[0] || "");
  const [yColumn, setYColumn] = useState(numericColumns[1] || numericColumns[0] || "");
  const [colorColumn, setColorColumn] = useState("");
  const [histColumn, setHistColumn] = useState(numericColumns[0] || "");
  const [histBins, setHistBins] = useState(10);

  const scatterPoints = useMemo(() => {
    if (!xColumn || !yColumn) return [];
    const points = [];
    for (const row of rows) {
      const x = toNumber(row[xColumn]);
      const y = toNumber(row[yColumn]);
      if (x === null || y === null) continue;
      const point = { x, y };
      if (colorColumn && row[colorColumn]) point.group = row[colorColumn];
      points.push(point);
    }
    return points;
  }, [rows, xColumn, yColumn, colorColumn]);

  const histBinsData = useMemo(
    () => (histColumn ? histogramBins(numericValues(rows, histColumn), histBins) : []),
    [rows, histColumn, histBins],
  );

  if (numericColumns.length === 0) {
    return <p className="hint">No numeric columns to plot yet - load a cohort with some measurements first.</p>;
  }

  return (
    <section>
      <h3>Scatter</h3>
      <label htmlFor="plot-x">x axis</label>
      <select id="plot-x" value={xColumn} onChange={(e) => setXColumn(e.target.value)}>
        {numericColumns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <label htmlFor="plot-y">y axis</label>
      <select id="plot-y" value={yColumn} onChange={(e) => setYColumn(e.target.value)}>
        {numericColumns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <label htmlFor="plot-color">color by (optional)</label>
      <select id="plot-color" value={colorColumn} onChange={(e) => setColorColumn(e.target.value)}>
        <option value="">(none)</option>
        {categoricalColumns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <ScatterPlot points={scatterPoints} xLabel={xColumn} yLabel={yColumn} />

      <h3>Histogram</h3>
      <label htmlFor="hist-column">metric</label>
      <select id="hist-column" value={histColumn} onChange={(e) => setHistColumn(e.target.value)}>
        {numericColumns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <label htmlFor="hist-bins">bins</label>
      <input
        id="hist-bins"
        type="number"
        min="3"
        max="30"
        value={histBins}
        onChange={(e) => setHistBins(Math.max(3, Math.min(30, Number(e.target.value) || 3)))}
      />
      <Histogram bins={histBinsData} />
    </section>
  );
}
