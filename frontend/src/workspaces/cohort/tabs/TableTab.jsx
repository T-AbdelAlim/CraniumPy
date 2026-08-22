import { useMemo, useState } from "react";
import { toNumber } from "../lib/stats.js";
import { downloadCohortExportXlsx } from "../../../api/cohort.js";

// plain sortable/filterable HTML table - not virtualized (~150 rows never
// needs it, see the plan's own note on this). filterText matches against
// every cell in a row, case-insensitively - simplest thing that actually
// helps ("show me the metopic patients", "find P00042") without a
// per-column filter UI this cohort size doesn't warrant.
export default function TableTab({ rows, columns, attachedColumnNames = [] }) {
  const [filterText, setFilterText] = useState("");
  const [sortColumn, setSortColumn] = useState(null);
  const [sortDir, setSortDir] = useState(1);

  const filtered = useMemo(() => {
    if (!filterText.trim()) return rows;
    const needle = filterText.trim().toLowerCase();
    return rows.filter((row) => columns.some((c) => String(row[c] ?? "").toLowerCase().includes(needle)));
  }, [rows, columns, filterText]);

  const sorted = useMemo(() => {
    if (!sortColumn) return filtered;
    return [...filtered].sort((a, b) => {
      const av = a[sortColumn] ?? "";
      const bv = b[sortColumn] ?? "";
      const an = toNumber(av);
      const bn = toNumber(bv);
      const cmp = an !== null && bn !== null ? an - bn : String(av).localeCompare(String(bv));
      return cmp * sortDir;
    });
  }, [filtered, sortColumn, sortDir]);

  const [exportStatus, setExportStatus] = useState("");

  function handleHeaderClick(column) {
    if (sortColumn === column) {
      setSortDir((d) => -d);
    } else {
      setSortColumn(column);
      setSortDir(1);
    }
  }

  async function handleExport() {
    setExportStatus("exporting...");
    try {
      // exports exactly what's currently shown (filtered + sorted), not
      // the full unfiltered table - "export what I'm looking at" is the
      // useful default here. attached Facial Anthropometrics columns (see
      // CohortWorkspace.jsx's attachedMeasurements) go to their own sheet
      // rather than folding into "cohort data" - keeps the primary cohort
      // sheet's own column set unchanged and avoids duplicating a
      // potentially large attached dataset into every export.
      const buildRows = (cols) => sorted.map((row) => Object.fromEntries(cols.map((c) => [c, String(row[c] ?? "")])));
      const coreColumns = columns.filter((c) => !attachedColumnNames.includes(c));
      const sheets = [{ title: "cohort data", columns: coreColumns, rows: buildRows(coreColumns) }];
      if (attachedColumnNames.length > 0) {
        const measurementColumns = ["cohort_id", ...attachedColumnNames];
        sheets.push({ title: "custom measurements", columns: measurementColumns, rows: buildRows(measurementColumns) });
      }
      await downloadCohortExportXlsx(sheets, "cohort_table.xlsx");
      setExportStatus("");
    } catch (err) {
      setExportStatus(`export failed: ${err.message}`);
    }
  }

  return (
    <section>
      <input
        type="text"
        placeholder="filter rows..."
        value={filterText}
        onChange={(e) => setFilterText(e.target.value)}
        className="cohort-ws-filter-input"
      />
      <p className="hint">
        {sorted.length} of {rows.length} rows shown. click a column header to sort.
      </p>
      <button type="button" className="button-subtle" onClick={handleExport}>
        export to Excel
      </button>
      {exportStatus && <p className="status-line">{exportStatus}</p>}
      <div className="cohort-ws-table-scroll">
        <table className="measurements-table cohort-ws-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} onClick={() => handleHeaderClick(c)} className="cohort-ws-sortable-header">
                  {c}
                  {sortColumn === c && (sortDir === 1 ? " ▲" : " ▼")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className="cohort-ws-col-name">
                    {row[c] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
