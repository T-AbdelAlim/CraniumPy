// blocking summary shown before committing a custom-measurements attach
// (CohortWorkspace.jsx's handleMeasurementsPicked) whenever the filename ->
// cohort_id join (api/routers/cohort.py's load_facial_measurements) found
// filenames it couldn't confidently resolve - never silently dropped or
// first-match-won, per the feature's own "handle unmatched/duplicate
// filenames clearly" requirement. same visual shell as ConfirmDialog.jsx,
// just with a scrollable breakdown instead of a one-line message.
export default function UnmatchedFilenamesDialog({ matchedCount, unmatched, ambiguous, onConfirm, onCancel }) {
  const ambiguousEntries = Object.entries(ambiguous);
  return (
    <div className="confirm-dialog-backdrop" onClick={onCancel}>
      <div className="confirm-dialog unmatched-filenames-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>Some measurement rows didn't match a patient</h3>
        <p>
          {matchedCount} row{matchedCount === 1 ? "" : "s"} matched a patient in this cohort by filename.
          {unmatched.length > 0 && ` ${unmatched.length} filename${unmatched.length === 1 ? "" : "s"} matched no patient.`}
          {ambiguousEntries.length > 0 &&
            ` ${ambiguousEntries.length} filename${ambiguousEntries.length === 1 ? "" : "s"} matched more than one patient.`}
        </p>
        {unmatched.length > 0 && (
          <div className="unmatched-filenames-section">
            <h4>No matching patient ({unmatched.length})</h4>
            <ul className="unmatched-filenames-list">
              {unmatched.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {ambiguousEntries.length > 0 && (
          <div className="unmatched-filenames-section">
            <h4>Matched more than one patient ({ambiguousEntries.length})</h4>
            <ul className="unmatched-filenames-list">
              {ambiguousEntries.map(([filename, cohortIds]) => (
                <li key={filename}>
                  {filename} - {cohortIds.join(", ")}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="confirm-dialog-actions">
          <button type="button" className="button-subtle" onClick={onCancel}>
            cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={matchedCount === 0}>
            load the {matchedCount} matched row{matchedCount === 1 ? "" : "s"} anyway
          </button>
        </div>
      </div>
    </div>
  );
}
