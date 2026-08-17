import { useMemo, useRef, useState } from "react";
import { loadCohortFile, loadDemoCohort, uploadCohortFile } from "../../api/cohort.js";
import { isDesktopApp, pickExcelFileNative } from "../../lib/desktop.js";
import { parseFormula, formulaColumns, evaluateFormula } from "./lib/safeFormula.js";
import { applyFilters } from "./lib/stats.js";
import FilterBar from "./FilterBar.jsx";
import OverviewTab from "./tabs/OverviewTab.jsx";
import TableTab from "./tabs/TableTab.jsx";
import MetricsTab from "./tabs/MetricsTab.jsx";
import StratifyTab from "./tabs/StratifyTab.jsx";
import PlotsTab from "./tabs/PlotsTab.jsx";
import MeanShapeTab from "./tabs/MeanShapeTab.jsx";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "table", label: "Table" },
  { id: "metrics", label: "Custom metrics" },
  { id: "stratify", label: "Stratify & compare" },
  { id: "plots", label: "Plots" },
  { id: "meanshape", label: "Mean shape" },
];

// batch/cohort analysis - a second top-level workspace alongside Patients
// (see components/shell/Shell.jsx's nav). loads an accumulated cohort
// spreadsheet (the file every patient export can optionally append a row
// to - see api/results_bundle.py's _upsert_cohort_xlsx) and explores it:
// overview/table, user-defined derived metrics, stratified comparisons with
// real statistical tests, plots, and - uniquely enabled by this app's NICP
// feature - a 3D mean shape across patients fit to the same template.
//
// owns the loaded columns/rows plus derivedColumns (custom metrics) here,
// at the top, since every tab below reads from the same merged view of the
// data - a metric added in the Custom metrics tab is immediately usable in
// Stratify/Plots without any tab-to-tab plumbing.
export default function CohortWorkspace() {
  const fileInputRef = useRef(null);
  const [columns, setColumns] = useState([]);
  const [rows, setRows] = useState([]);
  const [derivedColumns, setDerivedColumns] = useState([]); // [{name, formula, ast}]
  const [filters, setFilters] = useState([]); // [{column, values: string[]}]
  const [activeTab, setActiveTab] = useState("overview");
  const [loadStatus, setLoadStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const allColumns = useMemo(() => [...columns, ...derivedColumns.map((d) => d.name)], [columns, derivedColumns]);

  // every row with its custom-metric columns computed in, as plain numbers
  // (or "" when the formula couldn't be evaluated for that row - missing
  // input, same "blank, not zero" convention every column here follows).
  // recomputed whenever the raw rows or the metric definitions change, not
  // per-render otherwise - cheap at this cohort size (~150 rows) either way.
  const rowsWithDerived = useMemo(() => {
    if (derivedColumns.length === 0) return rows;
    return rows.map((row) => {
      const extra = {};
      for (const d of derivedColumns) {
        const value = evaluateFormula(d.ast, (name) => {
          const raw = row[name];
          if (raw === undefined || raw === "") return null;
          const n = Number(raw);
          return Number.isFinite(n) ? n : null;
        });
        extra[d.name] = value === null ? "" : value;
      }
      return { ...row, ...extra };
    });
  }, [rows, derivedColumns]);

  // the working subset every tab actually sees - see FilterBar's own
  // comment for why this lives here (one filter bar for the whole
  // workspace) rather than per-tab.
  const filteredRows = useMemo(() => applyFilters(rowsWithDerived, filters), [rowsWithDerived, filters]);

  function applyLoaded({ columns: newColumns, rows: newRows }) {
    setColumns(newColumns);
    setRows(newRows);
    setDerivedColumns([]);
    setFilters([]);
    setActiveTab("overview");
    setLoadStatus("");
  }

  // desktop: native file dialog, loads straight from the real path.
  // browser: just opens the plain <input type=file> below - the actual
  // load happens in handleFileInputChange once a file's picked, so this
  // branch doesn't touch loading/loadStatus itself (there's nothing to
  // report yet, and setting a "loading..." message here would leave it
  // stuck on screen if the user cancels the OS file dialog).
  async function handleLoadFile() {
    if (!isDesktopApp()) {
      fileInputRef.current.click();
      return;
    }
    setLoading(true);
    setLoadStatus("loading...");
    try {
      const path = await pickExcelFileNative(false, (msg) => setLoadStatus(`Couldn't open the file picker: ${msg}`));
      if (!path) {
        setLoadStatus("");
        return;
      }
      applyLoaded(await loadCohortFile(path));
    } catch (err) {
      setLoadStatus(`failed to load: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleFileInputChange(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    setLoading(true);
    setLoadStatus("loading...");
    try {
      applyLoaded(await uploadCohortFile(file));
    } catch (err) {
      setLoadStatus(`failed to load: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadDemo() {
    setLoading(true);
    setLoadStatus("loading demo cohort...");
    try {
      applyLoaded(await loadDemoCohort());
    } catch (err) {
      setLoadStatus(`failed to load demo cohort: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  // validates and stores a new custom metric - returns an error string to
  // show inline, or null on success. name collisions (with either a loaded
  // column or an existing metric) and unknown-column references are caught
  // here rather than left to surface as a confusing blank column later.
  function handleAddMetric(name, formula) {
    if (allColumns.includes(name)) return `"${name}" is already a column name`;
    let ast;
    try {
      ast = parseFormula(formula);
    } catch (err) {
      return err.message;
    }
    const unknown = [...formulaColumns(ast)].filter((c) => !allColumns.includes(c));
    if (unknown.length > 0) return `unknown column(s): ${unknown.join(", ")}`;
    setDerivedColumns((prev) => [...prev, { name, formula, ast }]);
    return null;
  }

  function handleRemoveMetric(name) {
    setDerivedColumns((prev) => prev.filter((d) => d.name !== name));
  }

  if (rows.length === 0) {
    return (
      <div className="cohort-ws cohort-ws-empty">
        <div className="cohort-ws-loader">
          <h2>Cohort analysis</h2>
          <p className="hint">
            Load an accumulated cohort spreadsheet (the file patient exports can append a row to) to explore it -
            custom metrics, stratified comparisons, statistical tests, plots, and 3D mean shapes across
            NICP-fitted patients.
          </p>
          <button type="button" onClick={handleLoadFile} disabled={loading}>
            load cohort file...
          </button>
          <button type="button" className="button-subtle" onClick={handleLoadDemo} disabled={loading}>
            load demo cohort (150 synthetic patients)
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={handleFileInputChange}
          />
          {loadStatus && <p className="status-line">{loadStatus}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="cohort-ws">
      <div className="cohort-ws-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={t.id === activeTab ? "cohort-ws-tab active" : "cohort-ws-tab"}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button type="button" className="button-subtle cohort-ws-reload-button" onClick={handleLoadFile} disabled={loading}>
          load a different cohort...
        </button>
        <input ref={fileInputRef} type="file" accept=".xlsx" className="hidden" onChange={handleFileInputChange} />
      </div>
      <FilterBar
        rows={rowsWithDerived}
        columns={allColumns}
        filters={filters}
        onFiltersChange={setFilters}
        filteredCount={filteredRows.length}
      />
      <div className="cohort-ws-content">
        {loadStatus && <p className="status-line">{loadStatus}</p>}
        {activeTab === "overview" && <OverviewTab rows={filteredRows} columns={allColumns} />}
        {activeTab === "table" && <TableTab rows={filteredRows} columns={allColumns} />}
        {activeTab === "metrics" && (
          <MetricsTab
            columns={columns}
            derivedColumns={derivedColumns}
            onAddMetric={handleAddMetric}
            onRemoveMetric={handleRemoveMetric}
          />
        )}
        {activeTab === "stratify" && <StratifyTab rows={filteredRows} columns={allColumns} />}
        {activeTab === "plots" && <PlotsTab rows={filteredRows} columns={allColumns} />}
        {activeTab === "meanshape" && <MeanShapeTab rows={filteredRows} filters={filters} />}
      </div>
    </div>
  );
}
