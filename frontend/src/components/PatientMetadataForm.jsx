// patient/visit fields for the summary spreadsheet/PDF export (see api/schemas.py's
// PatientMetadata) - lives in the bottom half of the left nav pane (see
// Shell.jsx), always visible once a mesh is loaded. file_name/file_path
// are pre-filled from the upload (see App.jsx's handleUploaded) but stay
// editable; every field is a plain string, so leaving one blank just means
// it comes through blank in the export - never omitted, see
// api/results_bundle.py's _metrics_row.
const SEX_OPTIONS = [
  { value: "", label: "unspecified" },
  { value: "female", label: "female" },
  { value: "male", label: "male" },
];

export default function PatientMetadataForm({
  metadata,
  onFieldChange,
  isDesktop,
  cohortMode,
  cohortPath,
  onCohortModeChange,
}) {
  return (
    <div className="metadata-form">
      <h3 className="metadata-form-title">Patient / visit</h3>

      <label>
        file name
        <input type="text" value={metadata.file_name} onChange={(e) => onFieldChange("file_name", e.target.value)} />
      </label>
      <label>
        file path
        <input type="text" value={metadata.file_path} onChange={(e) => onFieldChange("file_path", e.target.value)} />
      </label>
      <label>
        patient ID
        <input type="text" value={metadata.patient_id} onChange={(e) => onFieldChange("patient_id", e.target.value)} />
      </label>
      <label>
        sex
        <select value={metadata.sex} onChange={(e) => onFieldChange("sex", e.target.value)}>
          {SEX_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        imaging date
        <input
          type="date"
          value={metadata.date_imaging}
          onChange={(e) => onFieldChange("date_imaging", e.target.value)}
        />
      </label>
      <label>
        age at imaging (months)
        <input
          type="number"
          min="0"
          value={metadata.age_imaging}
          onChange={(e) => onFieldChange("age_imaging", e.target.value)}
        />
      </label>
      <label>
        treatment
        <input type="text" value={metadata.treatment} onChange={(e) => onFieldChange("treatment", e.target.value)} />
      </label>
      <label>
        age at surgery (months)
        <input
          type="number"
          min="0"
          value={metadata.age_surgery_months}
          onChange={(e) => onFieldChange("age_surgery_months", e.target.value)}
        />
      </label>
      <label>
        notes
        <input
          type="text"
          value={metadata.free_variable}
          onChange={(e) => onFieldChange("free_variable", e.target.value)}
        />
      </label>

      {isDesktop ? (
        <div className="cohort-control">
          <p className="hint">add this export's row to a cohort spreadsheet:</p>
          <label className="checkbox">
            <input
              type="radio"
              name="cohort-mode"
              checked={cohortMode === "none"}
              onChange={() => onCohortModeChange("none")}
            />
            don't add to a cohort
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="cohort-mode"
              checked={cohortMode === "create"}
              onChange={() => onCohortModeChange("create")}
            />
            create new cohort file...
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="cohort-mode"
              checked={cohortMode === "append"}
              onChange={() => onCohortModeChange("append")}
            />
            add to existing cohort file...
          </label>
          {cohortPath && <p className="hint">cohort file: {cohortPath}</p>}
        </div>
      ) : (
        <p className="hint">
          cohort spreadsheet accumulation needs the desktop app - a browser download can't append to a file on its
          own.
        </p>
      )}
    </div>
  );
}
