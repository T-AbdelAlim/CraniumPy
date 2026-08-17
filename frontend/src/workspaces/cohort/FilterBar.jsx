import { columnType, distinctValues } from "./lib/stats.js";

// row filters, applied before every tab (Overview/Table/Stratify/Plots/
// Mean shape all see the filtered rows, not the raw loaded ones) - this is
// what makes "pre-op only", "compare pre-op vs post-op within one
// treatment group", or "age at imaging between 2 and 3" possible: filter
// down first, then stratify/compute a mean shape on what's left. lives in
// CohortWorkspace (one filter bar for the whole workspace, not per-tab) so
// a filter set on one tab stays in effect when switching to another - the
// whole point is that every view of the cohort agrees on the same working
// subset.
//
// a filter's own control shape follows its column's type - categorical
// gets a checkbox per distinct value (kept to exact-value membership,
// there's no ordering to range over), numeric gets a min/max range (see
// lib/stats.js's applyFilters for both shapes).
// a sensible default column for a freshly-added filter - prefers
// "diagnosis" (the primary stratification variable this app's own domain
// cares about, same default StratifyTab's own group-by picks), otherwise
// the first categorical column that actually splits the cohort into more
// than one group and fewer groups than there are rows. an id-like column
// such as cohort_id/file_name is unique per row, so a fresh categorical
// filter for it would render one checkbox per patient - skip those rather
// than defaulting to the first column in the sheet regardless of whether
// it's usable.
function defaultFilterColumn(rows, columns, types, used) {
  const available = columns.filter((c) => !used.has(c));
  if (available.includes("diagnosis")) return "diagnosis";
  for (const c of available) {
    if (types[c] === "numeric") continue;
    const n = distinctValues(rows, c).length;
    if (n > 1 && n < rows.length) return c;
  }
  return available[0] || columns[0];
}

export default function FilterBar({ rows, columns, filters, onFiltersChange, filteredCount }) {
  if (columns.length === 0) return null;
  const types = Object.fromEntries(columns.map((c) => [c, columnType(rows, c)]));

  function addFilter() {
    const used = new Set(filters.map((f) => f.column));
    const column = defaultFilterColumn(rows, columns, types, used);
    onFiltersChange([...filters, blankFilter(column, types[column])]);
  }

  function updateFilter(index, next) {
    onFiltersChange(filters.map((f, i) => (i === index ? next : f)));
  }

  function removeFilter(index) {
    onFiltersChange(filters.filter((_, i) => i !== index));
  }

  function changeColumn(index, column) {
    updateFilter(index, blankFilter(column, types[column]));
  }

  function toggleValue(index, value) {
    const filter = filters[index];
    const values = filter.values.includes(value) ? filter.values.filter((v) => v !== value) : [...filter.values, value];
    updateFilter(index, { ...filter, values });
  }

  return (
    <div className="cohort-ws-filterbar">
      {filters.map((filter, i) => (
        <div key={i} className="cohort-ws-filter-row">
          <select value={filter.column} onChange={(e) => changeColumn(i, e.target.value)}>
            {columns.map((c) => (
              <option key={c} value={c}>{c}{types[c] === "numeric" ? " (numeric)" : ""}</option>
            ))}
          </select>
          {filter.type === "numeric" ? (
            <span className="cohort-ws-filter-range">
              <input
                type="number"
                placeholder="min"
                value={filter.min ?? ""}
                onChange={(e) => updateFilter(i, { ...filter, min: e.target.value === "" ? null : Number(e.target.value) })}
              />
              <span>to</span>
              <input
                type="number"
                placeholder="max"
                value={filter.max ?? ""}
                onChange={(e) => updateFilter(i, { ...filter, max: e.target.value === "" ? null : Number(e.target.value) })}
              />
            </span>
          ) : (
            <span className="cohort-ws-filter-values">
              {distinctValues(rows, filter.column).map((v) => (
                <label key={v} className="checkbox cohort-ws-filter-value">
                  <input type="checkbox" checked={filter.values.includes(v)} onChange={() => toggleValue(i, v)} />
                  {v}
                </label>
              ))}
            </span>
          )}
          <button type="button" className="button-subtle cohort-ws-inline-button" onClick={() => removeFilter(i)}>
            remove
          </button>
        </div>
      ))}
      <div className="cohort-ws-filter-row">
        <button type="button" className="button-subtle cohort-ws-inline-button" onClick={addFilter}>
          + add filter
        </button>
        {filters.length > 0 && (
          <span className="hint cohort-ws-filter-count">{filteredCount} of {rows.length} rows match</span>
        )}
      </div>
    </div>
  );
}

function blankFilter(column, type) {
  return type === "numeric" ? { column, type: "numeric", min: null, max: null } : { column, type: "categorical", values: [] };
}
