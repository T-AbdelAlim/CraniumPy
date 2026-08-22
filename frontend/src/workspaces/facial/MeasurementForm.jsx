import { useState } from "react";
import { MEASUREMENT_TYPE_LABELS, pointCountHint, pointCountValid } from "./lib/points.js";

const TYPES = ["linear", "angular", "area"];

// "Add Measurement" - a type picker, then (once a type's picked and the
// user has ctrl-clicked enough points on the viewer - see
// FacialWorkspace.jsx's handlePick) name/abbreviation fields and a Confirm
// button. pendingType/pendingPointCount are owned by FacialWorkspace (the
// points themselves live in its own `points` dict, shared with every
// confirmed measurement) - this component is just the form chrome around
// that shared state.
export default function MeasurementForm({ pendingType, pendingPointCount, existingNames, existingAbbreviations, onStartType, onConfirm, onCancel }) {
  const [name, setName] = useState("");
  const [abbreviation, setAbbreviation] = useState("");
  const [geodesic, setGeodesic] = useState(false);

  if (!pendingType) {
    return (
      <div className="facial-add-measurement">
        <span className="hint">add measurement:</span>
        {TYPES.map((t) => (
          <button type="button" key={t} onClick={() => onStartType(t)}>
            {MEASUREMENT_TYPE_LABELS[t]}
          </button>
        ))}
      </div>
    );
  }

  const countOk = pointCountValid(pendingType, pendingPointCount);
  const trimmedName = name.trim();
  const trimmedAbbr = abbreviation.trim();
  const nameTaken = trimmedName.length > 0 && existingNames.includes(trimmedName);
  const abbrTaken = trimmedAbbr.length > 0 && existingAbbreviations.includes(trimmedAbbr);
  const canConfirm = countOk && trimmedName.length > 0 && trimmedAbbr.length > 0 && !nameTaken && !abbrTaken;

  function handleConfirm() {
    if (!canConfirm) return;
    onConfirm({ name: trimmedName, abbreviation: trimmedAbbr, geodesic });
    setName("");
    setAbbreviation("");
    setGeodesic(false);
  }

  function handleCancel() {
    setName("");
    setAbbreviation("");
    setGeodesic(false);
    onCancel();
  }

  return (
    <div className="facial-add-measurement facial-add-measurement-pending">
      <p className="hint">
        {MEASUREMENT_TYPE_LABELS[pendingType]}: ctrl-click on the mesh to place points ({pointCountHint(pendingType)}) -{" "}
        {pendingPointCount} placed so far.
        {pendingType === "area" && countOk && " you can keep adding points, or confirm now to close the boundary."}
      </p>
      <label>
        name
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bizygomatic width" />
      </label>
      <label>
        abbreviation
        <input type="text" value={abbreviation} onChange={(e) => setAbbreviation(e.target.value)} placeholder="e.g. ZW" />
      </label>
      {pendingType === "linear" && (
        <label className="checkbox">
          <input type="checkbox" checked={geodesic} onChange={(e) => setGeodesic(e.target.checked)} />
          shortest distance along the mesh surface (geodesic), instead of a straight line
        </label>
      )}
      {nameTaken && <p className="hint facial-form-warning">a measurement named "{trimmedName}" already exists</p>}
      {abbrTaken && <p className="hint facial-form-warning">the abbreviation "{trimmedAbbr}" is already in use</p>}
      <div className="facial-add-measurement-actions">
        <button type="button" className="button-subtle" onClick={handleCancel}>
          cancel
        </button>
        <button type="button" onClick={handleConfirm} disabled={!canConfirm}>
          confirm measurement
        </button>
      </div>
    </div>
  );
}
