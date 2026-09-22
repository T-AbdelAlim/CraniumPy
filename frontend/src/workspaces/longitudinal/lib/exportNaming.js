// {patientID}_{kind}_t{start}_t{end} - the folder name both the Trends
// tab's "export results" button and 3D Morphing's "export video" button
// create inside the user-picked destination folder (see
// LongitudinalWorkspace.jsx's exportDestDir) - kind is "trend" or "morph".
// patientId comes from whatever the baseline (first) slot's own label
// already carries - the one thing in this workspace that already
// resembles a "patient ID" field (see TimepointSlot.jsx's own label
// input, and App.jsx's handleStageForLongitudinal, which seeds it from
// patientMetadata.patient_id when staged from the Patients workspace) -
// falling back to a plain default when it's still just the untouched
// "Timepoint N" placeholder (an empty slot.label, not a real value
// someone typed). includedIndices are the actual slot positions this
// particular export covers (every ready slot for Trends, since it always
// plots all of them; only the ones picked for the sequence for Morphing) -
// start/end reflect what's really in the export, not just the workspace's
// own slot count.
export function exportFolderName(kind, slots, includedIndices) {
  const patientId = (slots[0]?.label || "").trim() || "patient";
  const start = Math.min(...includedIndices);
  const end = Math.max(...includedIndices);
  return `${patientId}_${kind}_t${start}_t${end}`;
}
