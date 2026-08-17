import { useState } from "react";
import InfoTooltip from "../../../components/InfoTooltip.jsx";

const FORMULA_EXPLAINER =
  "numbers, + - * / ( ), and column names only - e.g. cephalic_index / age_imaging. " +
  "no functions, no other operators. a column that's blank for a given patient makes the " +
  "whole formula blank for that patient too, rather than treating it as zero.";

// name + formula box for deriving a new numeric column from existing ones -
// evaluated by lib/safeFormula.js's constrained parser (not eval/new
// Function - see that file's own comment for why), so this box can only
// ever compute arithmetic, never run arbitrary code. added columns are
// usable everywhere else in the workspace (Table, Stratify, Plots) exactly
// like a column that came from the spreadsheet itself.
export default function MetricsTab({ columns, derivedColumns, onAddMetric, onRemoveMetric }) {
  const [name, setName] = useState("");
  const [formula, setFormula] = useState("");
  const [error, setError] = useState("");

  function handleAdd() {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("give the metric a name");
      return;
    }
    const result = onAddMetric(trimmedName, formula);
    if (result) {
      setError(result);
      return;
    }
    setName("");
    setFormula("");
    setError("");
  }

  return (
    <section>
      <p className="hint">
        available columns: {columns.join(", ")}
      </p>

      <label htmlFor="metric-name">
        name
        <InfoTooltip text={FORMULA_EXPLAINER} />
      </label>
      <input
        id="metric-name"
        type="text"
        placeholder="e.g. index_per_age"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <label htmlFor="metric-formula">formula</label>
      <input
        id="metric-formula"
        type="text"
        placeholder="e.g. cephalic_index / age_imaging"
        value={formula}
        onChange={(e) => setFormula(e.target.value)}
      />
      <button type="button" onClick={handleAdd}>
        add metric
      </button>
      {error && <p className="status-line cohort-ws-error">{error}</p>}

      {derivedColumns.length > 0 && (
        <>
          <h3>Custom metrics</h3>
          <table className="measurements-table cohort-ws-table">
            <thead>
              <tr>
                <th>name</th>
                <th>formula</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {derivedColumns.map((d) => (
                <tr key={d.name}>
                  <td className="cohort-ws-col-name">{d.name}</td>
                  <td className="cohort-ws-col-name">{d.formula}</td>
                  <td>
                    <button type="button" className="button-subtle cohort-ws-inline-button" onClick={() => onRemoveMetric(d.name)}>
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
