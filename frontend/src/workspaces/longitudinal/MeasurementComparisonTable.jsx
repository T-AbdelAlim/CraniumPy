// N-column measurement comparison - one column per slot that has finished
// measuring (see TimepointSlot's measureAndReport), one row per metric.
// deliberately a smaller field set than the Patients workspace's own
// AnalysisPanel.jsx (which has per-metric InfoTooltip explainers this
// summary table skips) - this is the "how did the numbers change" view,
// not a replacement for the full single-timepoint readout.
const FIELDS = [
  { group: "craniometrics", key: "depth_mm", label: "Head length (OFD)", unit: "mm" },
  { group: "craniometrics", key: "breadth_mm", label: "Head width (BPD)", unit: "mm" },
  { group: "craniometrics", key: "cephalic_index", label: "Cephalic index", unit: "" },
  { group: "craniometrics", key: "circumference_cm", label: "Head circumference", unit: "cm" },
  { group: "frontal_bossing", key: "angle_deg", label: "Frontal bossing angle", unit: "deg" },
  { group: "metopic", key: "frontal_angle_deg", label: "Metopic frontal angle", unit: "deg" },
  { group: "metopic", key: "ridge_protrusion_mm", label: "Ridge protrusion", unit: "mm" },
  { group: "metopic", key: "parabolic_deviation_index", label: "Overall shape deviation index", unit: "mm" },
  { group: "asymmetry", key: "mean_asymmetry_index", label: "Asymmetry index", unit: "mm" },
];

function fmt(value) {
  return typeof value === "number" ? value.toFixed(2) : "-";
}

export default function MeasurementComparisonTable({ slots }) {
  const ready = slots.filter((s) => s.ready && s.measurements);
  if (ready.length === 0) return <p className="hint">Register at least one timepoint to see its measurements here.</p>;

  const rows = FIELDS.filter((f) => ready.some((s) => s.measurements[f.group]?.[f.key] !== undefined));

  return (
    <div className="cohort-ws-table-scroll">
      <table className="measurements-table longitudinal-comparison-table">
        <thead>
          <tr>
            <th>Metric</th>
            {ready.map((s, i) => (
              <th key={s.id}>
                <span className="viewer-legend-swatch" style={{ background: s.color, display: "inline-block", marginRight: "0.4em" }} />
                {s.label || `Timepoint ${i + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={`${f.group}.${f.key}`}>
              <td>{f.label}</td>
              {ready.map((s) => {
                const value = s.measurements[f.group]?.[f.key];
                return (
                  <td key={s.id}>
                    {value === undefined ? "-" : `${fmt(value)} ${f.unit}`.trim()}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
