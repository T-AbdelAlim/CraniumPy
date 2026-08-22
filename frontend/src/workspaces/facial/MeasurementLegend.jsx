import { MEASUREMENT_TYPE_UNITS } from "./lib/points.js";

// shared by DefinePanel (live values against the template) and
// BatchReviewPanel (the currently-reviewed file's own values) - same
// swatch/name/value row either way, just fed different values/valueErrors.
export default function MeasurementLegend({ measurements, values, valueErrors, onRemove }) {
  if (measurements.length === 0) {
    return <p className="hint">No measurements defined yet.</p>;
  }
  return (
    <ul className="facial-legend">
      {measurements.map((m) => {
        const value = values?.[m.id];
        const error = valueErrors?.[m.id];
        const unit = MEASUREMENT_TYPE_UNITS[m.type];
        return (
          <li key={m.id} className="facial-legend-row">
            <span className="facial-legend-swatch" style={{ background: m.color }} />
            <span className="facial-legend-label">
              {m.name} ({m.abbreviation})
            </span>
            <span className={error ? "facial-legend-value facial-legend-value-error" : "facial-legend-value"} title={error || ""}>
              {error ? "—" : value == null ? "…" : `${value.toFixed(2)} ${unit}`}
            </span>
            {onRemove && (
              <button type="button" className="button-subtle" onClick={() => onRemove(m.id)}>
                remove
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
