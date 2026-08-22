import { useEffect, useMemo, useRef, useState } from "react";
import { loadCohortFile, loadDemoCohort, loadFacialMeasurements, uploadCohortFile } from "../../api/cohort.js";
import { isDesktopApp, pickExcelFileNative } from "../../lib/desktop.js";
import { parseFormula, formulaColumns, evaluateFormula } from "./lib/safeFormula.js";
import { applyFilters } from "./lib/stats.js";
import FilterBar from "./FilterBar.jsx";
import CustomMeasurementsPanel from "./CustomMeasurementsPanel.jsx";
import UnmatchedFilenamesDialog from "./UnmatchedFilenamesDialog.jsx";
import OverviewTab from "./tabs/OverviewTab.jsx";
import TableTab from "./tabs/TableTab.jsx";
import MetricsTab from "./tabs/MetricsTab.jsx";
import StratifyTab from "./tabs/StratifyTab.jsx";
import PlotsTab from "./tabs/PlotsTab.jsx";
import MeanShapeTab from "./tabs/MeanShapeTab.jsx";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "table", label: "Table" },
  { id: "stratify", label: "Stratify & compare" },
  { id: "plots", label: "Plots" },
  { id: "meanshape", label: "Mean shape" },
  { id: "metrics", label: "Custom metrics" },
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
export default function CohortWorkspace({ onSnapshotChange, initialSnapshot }) {
  const fileInputRef = useRef(null);
  // lazy initializers - seeded once from a preserved snapshot (see App.jsx's
  // cohortSnapshot/handleRestorePrevious) when returning to this workspace,
  // same as a fresh load otherwise. this component still fully unmounts on
  // every appMode switch (see App.jsx's own comment on that tradeoff) - the
  // snapshot is what lets "load previous workspace" reconstruct the same
  // scene despite that, without needing to keep it mounted-but-hidden.
  const [columns, setColumns] = useState(() => initialSnapshot?.columns ?? []);
  const [rows, setRows] = useState(() => initialSnapshot?.rows ?? []);
  const [derivedColumns, setDerivedColumns] = useState(() => initialSnapshot?.derivedColumns ?? []); // [{name, formula, ast}]
  const [filters, setFilters] = useState(() => initialSnapshot?.filters ?? []); // [{column, values: string[]}]
  const [activeTab, setActiveTab] = useState(() => initialSnapshot?.activeTab ?? "overview");
  const [loadStatus, setLoadStatus] = useState("");
  const [loading, setLoading] = useState(false);

  // the loaded cohort file's own real path (desktop only - a browser
  // upload/the shipped demo never has one) - needed to find this cohort's
  // id-mapping file when attaching custom measurements below (see
  // CustomMeasurementsPanel.jsx/api/routers/cohort.py's
  // load_facial_measurements, which joins by filename against that file).
  const [cohortPath, setCohortPath] = useState(() => initialSnapshot?.cohortPath ?? null);

  // a Facial Anthropometrics batch export attached to this cohort, kept
  // fully separate from columns/rows/derivedColumns (never merged into the
  // core cohort table - see rowsWithAttached below and the plan's own
  // "keep the custom measurement dataset separate ... in memory and on
  // disk wherever possible"). { columns, rowsByCohortId, legend,
  // sourceFileName } | null.
  const [attachedMeasurements, setAttachedMeasurements] = useState(() => initialSnapshot?.attachedMeasurements ?? null);
  const [measurementsStatus, setMeasurementsStatus] = useState("");
  // a load whose match came back with unmatched/ambiguous filenames,
  // held here until the user confirms via UnmatchedFilenamesDialog -
  // never committed to attachedMeasurements silently.
  const [pendingMeasurements, setPendingMeasurements] = useState(null);

  // reports this workspace's own lightweight, JSON-safe state up to
  // App.jsx on every change - all plain loaded data (no 3D/GPU objects),
  // cheap to keep current continuously rather than only capturing it right
  // before a switch away.
  useEffect(() => {
    onSnapshotChange?.({ columns, rows, derivedColumns, filters, activeTab, cohortPath, attachedMeasurements });
  }, [columns, rows, derivedColumns, filters, activeTab, cohortPath, attachedMeasurements, onSnapshotChange]);

  const allColumns = useMemo(
    () => [...columns, ...derivedColumns.map((d) => d.name), ...(attachedMeasurements?.columns ?? [])],
    [columns, derivedColumns, attachedMeasurements],
  );

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

  // non-destructively folds the attached measurement columns into each
  // row by cohort_id - an O(rows.length) hash lookup per row (rowsByCohortId
  // was already built once, server-side, on attach), not a repeated join;
  // modeled on rowsWithDerived's own spread pattern just above, keyed by an
  // external id instead of computed in-row. a row whose cohort_id has no
  // attached measurement (or no attachment loaded at all) is untouched.
  const rowsWithAttached = useMemo(() => {
    if (!attachedMeasurements) return rowsWithDerived;
    return rowsWithDerived.map((row) => ({
      ...row,
      ...(attachedMeasurements.rowsByCohortId[row.cohort_id] ?? {}),
    }));
  }, [rowsWithDerived, attachedMeasurements]);

  // the working subset every tab actually sees - see FilterBar's own
  // comment for why this lives here (one filter bar for the whole
  // workspace) rather than per-tab.
  const filteredRows = useMemo(() => applyFilters(rowsWithAttached, filters), [rowsWithAttached, filters]);

  function applyLoaded({ columns: newColumns, rows: newRows }) {
    setColumns(newColumns);
    setRows(newRows);
    setDerivedColumns([]);
    setFilters([]);
    setActiveTab("overview");
    setLoadStatus("");
    setCohortPath(null);
    setAttachedMeasurements(null);
    setMeasurementsStatus("");
    setPendingMeasurements(null);
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
      setCohortPath(path);
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

  // "load a different cohort..." (top right, once a cohort is already
  // loaded) - back to the starting screen (load a file / load the demo),
  // not straight into the file picker: the demo cohort is only reachable
  // from that screen, and jumping straight to a file dialog meant there
  // was no way back to it (or to just reconsider) without a page reload.
  function handleGoToStart() {
    setColumns([]);
    setRows([]);
    setDerivedColumns([]);
    setFilters([]);
    setActiveTab("overview");
    setLoadStatus("");
    setCohortPath(null);
    setAttachedMeasurements(null);
    setMeasurementsStatus("");
    setPendingMeasurements(null);
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

  // CustomMeasurementsPanel's file pick callback - runs the filename ->
  // cohort_id join server-side (api/routers/cohort.py's
  // load_facial_measurements) and either commits straight away (every
  // filename matched cleanly) or holds the result for
  // UnmatchedFilenamesDialog to confirm - never silently drops or
  // first-match-wins an unmatched/ambiguous filename.
  async function handleMeasurementsPicked(path, errorMsg) {
    if (errorMsg) {
      setMeasurementsStatus(errorMsg);
      return;
    }
    if (!path || !cohortPath) return;
    setMeasurementsStatus("matching measurements to patients...");
    try {
      const result = await loadFacialMeasurements(cohortPath, path);
      const sourceFileName = path.split(/[\\/]/).pop();
      const hasIssues = result.unmatched.length > 0 || Object.keys(result.ambiguous).length > 0;
      if (hasIssues) {
        setPendingMeasurements({ ...result, sourceFileName });
        setMeasurementsStatus("");
      } else {
        setAttachedMeasurements({ ...result, sourceFileName });
        setMeasurementsStatus("");
      }
    } catch (err) {
      setMeasurementsStatus(`failed to attach measurements: ${err.message}`);
    }
  }

  function handleConfirmPendingMeasurements() {
    if (!pendingMeasurements) return;
    setAttachedMeasurements(pendingMeasurements);
    setPendingMeasurements(null);
  }

  function handleCancelPendingMeasurements() {
    setPendingMeasurements(null);
  }

  function handleDetachMeasurements() {
    setAttachedMeasurements(null);
    setMeasurementsStatus("");
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
        <button type="button" className="button-subtle cohort-ws-reload-button" onClick={handleGoToStart}>
          load a different cohort...
        </button>
      </div>
      <CustomMeasurementsPanel
        cohortPath={cohortPath}
        attachedMeasurements={attachedMeasurements}
        status={measurementsStatus}
        onPick={handleMeasurementsPicked}
        onDetach={handleDetachMeasurements}
      />
      <FilterBar
        rows={rowsWithAttached}
        columns={allColumns}
        filters={filters}
        onFiltersChange={setFilters}
        filteredCount={filteredRows.length}
      />
      <div className="cohort-ws-content">
        {loadStatus && <p className="status-line">{loadStatus}</p>}
        {activeTab === "overview" && <OverviewTab rows={filteredRows} columns={allColumns} />}
        {activeTab === "table" && (
          <TableTab rows={filteredRows} columns={allColumns} attachedColumnNames={attachedMeasurements?.columns ?? []} />
        )}
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
      {pendingMeasurements && (
        <UnmatchedFilenamesDialog
          matchedCount={Object.keys(pendingMeasurements.rowsByCohortId).length}
          unmatched={pendingMeasurements.unmatched}
          ambiguous={pendingMeasurements.ambiguous}
          onConfirm={handleConfirmPendingMeasurements}
          onCancel={handleCancelPendingMeasurements}
        />
      )}
    </div>
  );
}
