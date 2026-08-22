import { isDesktopApp, pickExcelFileNative } from "../../lib/desktop.js";

// toolbar control for attaching a Facial Anthropometrics batch export (see
// api/facial.js's downloadFacialBatchExport) to the currently-loaded
// cohort, joined by mesh filename -> cohort_id (CohortWorkspace.jsx's
// attachedMeasurements state/rowsWithAttached merge). deliberately separate
// from MetricsTab.jsx's custom-formula metrics - this is an external-file
// join against a dataset kept out of the core cohort table, not a
// single-row arithmetic expression.
//
// desktop-only, and only once a cohort has actually been loaded from a real
// path (cohortPath) - matching by filename requires this cohort's own
// id-mapping file on disk (see api/results_bundle.py's _id_mapping_path),
// which a browser-uploaded or the shipped demo cohort doesn't have.
export default function CustomMeasurementsPanel({ cohortPath, attachedMeasurements, status, onPick, onDetach }) {
  if (!isDesktopApp() || !cohortPath) {
    return (
      <div className="cohort-custom-measurements">
        <p className="hint">
          Attaching custom Facial Anthropometrics measurements requires a cohort file loaded from disk (desktop
          app only).
        </p>
      </div>
    );
  }

  async function handlePick() {
    const path = await pickExcelFileNative(false, (msg) => onPick(null, msg));
    if (path) onPick(path, null);
  }

  return (
    <div className="cohort-custom-measurements">
      {attachedMeasurements ? (
        <>
          <span className="cohort-custom-measurements-summary">
            {attachedMeasurements.columns.length} custom measurement
            {attachedMeasurements.columns.length === 1 ? "" : "s"} attached
            {attachedMeasurements.sourceFileName ? ` from ${attachedMeasurements.sourceFileName}` : ""}
          </span>
          <button type="button" className="button-subtle" onClick={handlePick}>
            attach a different file...
          </button>
          <button type="button" className="button-subtle" onClick={onDetach}>
            detach
          </button>
        </>
      ) : (
        <button type="button" className="button-subtle" onClick={handlePick}>
          attach custom measurements...
        </button>
      )}
      {status && <p className="status-line">{status}</p>}
    </div>
  );
}
