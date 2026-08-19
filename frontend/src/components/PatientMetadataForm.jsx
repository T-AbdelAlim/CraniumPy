import { useEffect, useRef } from "react";

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

// diagnosis is a plain text field first and foremost (so anyone using this
// for something other than craniosynostosis can just type directly into
// it - see below), with this dropdown as an optional quick-fill on top.
// picking an option here overwrites the text field with that value rather
// than binding to it, so the field stays freely editable afterward (e.g.
// typing the actual syndrome name in after picking "Syndromic").
const DIAGNOSIS_QUICK_PICKS = [
  "Sagittal synostosis",
  "Unicoronal synostosis",
  "Bicoronal synostosis",
  "Metopic synostosis",
  "Lambdoid synostosis",
  "Multisuture / complex synostosis",
  "Syndromic - ",
  "Unknown",
];

const FOLLOWUP_TIMEPOINTS = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"];

const SURGICAL_STATUS_OPTIONS = [
  { value: "pre-op", label: "pre-op" },
  { value: "post-op", label: "post-op" },
  { value: "no_surgery", label: "no surgery" },
];

// whole completed months between two ISO date strings ("" if either is
// missing/unparseable, or target is before dob) - backs the auto-computed
// age at imaging/intervention fields below. "completed months" (not a
// rounded fraction) matches how age-in-months is normally reported
// clinically: someone isn't "6 months old" until a full 6 calendar months
// have actually elapsed.
function ageInMonths(dobStr, targetStr) {
  if (!dobStr || !targetStr) return "";
  const dob = new Date(dobStr);
  const target = new Date(targetStr);
  if (Number.isNaN(dob.getTime()) || Number.isNaN(target.getTime())) return "";
  let months = (target.getFullYear() - dob.getFullYear()) * 12 + (target.getMonth() - dob.getMonth());
  if (target.getDate() < dob.getDate()) months -= 1;
  return months < 0 ? "" : String(months);
}

export default function PatientMetadataForm({
  metadata,
  onFieldChange,
  isDesktop,
  cohortMode,
  cohortPath,
  onCohortModeChange,
  samePatientMode,
  onSamePatientModeChange,
}) {
  const diagnosisInputRef = useRef(null);
  // greyed out while samePatientMode is on - everything about the PATIENT
  // rather than this particular image, so it doesn't need retyping for a
  // follow-up scan of someone already filled in (see App.jsx's
  // handleUploaded, which preserves exactly these fields across a
  // same-patient upload and blanks everything else).
  const frozen = samePatientMode;

  // both age fields recompute whenever date_of_birth or the relevant date
  // changes, overwriting whatever was there - a fresh useEffect run only
  // fires on one of those two inputs actually changing, so a manual edit
  // to the age field itself (after auto-fill) sticks until either date
  // changes again. no date_of_birth on file just means these stay exactly
  // what they always were - plain, manually-typed fields.
  useEffect(() => {
    const computed = ageInMonths(metadata.date_of_birth, metadata.date_imaging);
    if (computed !== "") onFieldChange("age_imaging", computed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metadata.date_of_birth, metadata.date_imaging]);

  useEffect(() => {
    const computed = ageInMonths(metadata.date_of_birth, metadata.date_of_intervention);
    if (computed !== "") onFieldChange("age_intervention_months", computed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metadata.date_of_birth, metadata.date_of_intervention]);

  // image_timing is stored as one flat string (see api/schemas.py's
  // PatientMetadata) - "t0" (initial image), "t1".."t9" (a follow-up
  // image's sequence number), or "" (unspecified) - so a cohort
  // spreadsheet can stratify on a single column rather than two. this
  // form still edits it as two controls (a type dropdown + the follow-up
  // timepoint dropdown), derived from that one string rather than kept as
  // separate local state, so it stays in sync if metadata.image_timing
  // ever changes from outside this form (e.g. a fresh upload resetting
  // it). picking "follow-up image" defaults straight to "t1" (rather than
  // leaving an ambiguous "chosen but no timepoint yet" state) so the type
  // dropdown's own selection is always fully derivable from the stored
  // string alone.
  const timingType = metadata.image_timing === "" ? "" : metadata.image_timing === "t0" ? "t0" : "followup";
  const followupTimepoint = timingType === "followup" ? metadata.image_timing : "";

  function handleTimingTypeChange(type) {
    if (type === "t0") onFieldChange("image_timing", "t0");
    else if (type === "followup") onFieldChange("image_timing", "t1");
    else onFieldChange("image_timing", "");
  }

  function handleDiagnosisQuickPick(value) {
    if (!value) return;
    onFieldChange("diagnosis", value);
    // "Syndromic - " needs the actual syndrome name typed right after it -
    // land the cursor there instead of just filling the field and leaving
    // the user to find it themselves.
    requestAnimationFrame(() => {
      const el = diagnosisInputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(value.length, value.length);
    });
  }

  return (
    <div className="metadata-form">
      <h3 className="metadata-form-title">Patient / visit</h3>

      <label className="checkbox metadata-same-patient-toggle">
        <input
          type="checkbox"
          checked={samePatientMode}
          onChange={(e) => onSamePatientModeChange(e.target.checked)}
        />
        same patient, new image
      </label>
      {frozen && (
        <p className="hint">
          patient details below are locked - only imaging date, image timing, and notes reset for the new upload.
        </p>
      )}

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
        <input
          type="text"
          disabled={frozen}
          value={metadata.patient_id}
          onChange={(e) => onFieldChange("patient_id", e.target.value)}
        />
      </label>
      <label>
        date of birth
        <input
          type="date"
          disabled={frozen}
          value={metadata.date_of_birth}
          onChange={(e) => onFieldChange("date_of_birth", e.target.value)}
        />
      </label>
      <label>
        diagnosis
        <input
          ref={diagnosisInputRef}
          type="text"
          disabled={frozen}
          placeholder="craniosynostosis subtype, syndrome, or type your own"
          value={metadata.diagnosis}
          onChange={(e) => onFieldChange("diagnosis", e.target.value)}
        />
        <select disabled={frozen} value="" onChange={(e) => handleDiagnosisQuickPick(e.target.value)}>
          <option value="">quick pick...</option>
          {DIAGNOSIS_QUICK_PICKS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <label>
        sex
        <select disabled={frozen} value={metadata.sex} onChange={(e) => onFieldChange("sex", e.target.value)}>
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
        {metadata.date_of_birth && <span className="hint">auto-computed from date of birth</span>}
      </label>
      <label>
        image timing
        <select value={timingType} onChange={(e) => handleTimingTypeChange(e.target.value)}>
          <option value="">unspecified</option>
          <option value="t0">initial image (t0)</option>
          <option value="followup">follow-up image</option>
        </select>
      </label>
      {timingType === "followup" && (
        <label>
          follow-up timepoint
          <select value={followupTimepoint} onChange={(e) => onFieldChange("image_timing", e.target.value)}>
            {FOLLOWUP_TIMEPOINTS.map((tp) => (
              <option key={tp} value={tp}>
                {tp}
              </option>
            ))}
          </select>
        </label>
      )}
      {timingType !== "" && (
        <div className="metadata-surgical-status">
          <p className="hint">
            surgical status{!metadata.surgical_status && <span className="metadata-required-hint"> (required)</span>}
          </p>
          {SURGICAL_STATUS_OPTIONS.map((opt) => (
            <label key={opt.value} className="checkbox">
              <input
                type="radio"
                name="surgical-status"
                checked={metadata.surgical_status === opt.value}
                onChange={() => onFieldChange("surgical_status", opt.value)}
              />
              {opt.label}
            </label>
          ))}
        </div>
      )}
      <label>
        treatment
        <input
          type="text"
          disabled={frozen}
          value={metadata.treatment}
          onChange={(e) => onFieldChange("treatment", e.target.value)}
        />
      </label>
      <label>
        date of intervention
        <input
          type="date"
          disabled={frozen}
          value={metadata.date_of_intervention}
          onChange={(e) => onFieldChange("date_of_intervention", e.target.value)}
        />
      </label>
      <label>
        age at intervention (months)
        <input
          type="number"
          min="0"
          disabled={frozen}
          value={metadata.age_intervention_months}
          onChange={(e) => onFieldChange("age_intervention_months", e.target.value)}
        />
        {metadata.date_of_birth && <span className="hint">auto-computed from date of birth</span>}
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
