import { columnType, completeness } from "../lib/stats.js";

// at-a-glance shape of the loaded cohort - row/column counts, per-column
// type + completeness, and a quick health-check listing exactly which
// columns are sparse and by how much. the point is to answer "is this data
// actually usable for what I'm about to do" before diving into Table/
// Stratify/Plots - a stratified comparison on a column that's 40% blank is
// still valid, just worth knowing going in.
export default function OverviewTab({ rows, columns }) {
  const summary = columns.map((column) => ({
    column,
    type: columnType(rows, column),
    completeness: completeness(rows, column),
  }));
  const incomplete = summary.filter((s) => s.completeness < 1).sort((a, b) => a.completeness - b.completeness);

  return (
    <section>
      <div className="cohort-ws-stat-row">
        <div className="cohort-ws-stat">
          <span className="cohort-ws-stat-value">{rows.length}</span>
          <span className="cohort-ws-stat-label">patients</span>
        </div>
        <div className="cohort-ws-stat">
          <span className="cohort-ws-stat-value">{columns.length}</span>
          <span className="cohort-ws-stat-label">columns</span>
        </div>
      </div>

      {incomplete.length > 0 && (
        <>
          <h3>Health check</h3>
          <ul className="cohort-ws-health-list">
            {incomplete.map((s) => (
              <li key={s.column}>
                <strong>{Math.round((1 - s.completeness) * rows.length)}</strong> row(s) missing{" "}
                <code>{s.column}</code>
                <span className="hint">({Math.round(s.completeness * 100)}% complete)</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Columns</h3>
      <table className="measurements-table cohort-ws-table">
        <thead>
          <tr>
            <th>column</th>
            <th>type</th>
            <th>complete</th>
          </tr>
        </thead>
        <tbody>
          {summary.map((s) => (
            <tr key={s.column}>
              <td className="cohort-ws-col-name">{s.column}</td>
              <td>{s.type}</td>
              <td>{Math.round(s.completeness * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
