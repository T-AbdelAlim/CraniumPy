// dynamic landmark-point identity for the Facial Anthropometrics workspace -
// unlike the Patients workspace's fixed 3-4 named landmarks (lib/landmarks.js's
// LANDMARK_NAMES), a measurement here can reference any number of arbitrary
// points, so identity has to be generated, not a constant list.

// the highest "pN" numeric suffix already in use among `points` (0 if
// there are none) - used to SEED a synchronous, monotonically-incrementing
// counter (see FacialWorkspace.jsx's nextPointIndexRef), not to generate an
// id directly on every pick. an earlier version generated each id as
// `nextPointId(Object.keys(points))` computed AFTER an async pick's network
// round trip resolved - two picks fired within the same round-trip window
// both read the same pre-await `points` and could compute the identical
// id, silently collapsing two distinct landmarks into one (a Linear
// measurement whose two point_ids were actually the same point, reporting
// 0.00mm instead of erroring or staying distinct). seeding a plain counter
// from this - by MAX index, not just Object.keys(points).length - matters
// because a restored snapshot's points can have gaps (a measurement
// removal only deletes the points it alone used - see
// handleRemoveMeasurement - so "p2" can be gone while "p3" remains); a
// length-based seed could then hand out "p3" again and collide with the
// one still there.
export function maxPointIndex(points) {
  let max = 0;
  for (const id of Object.keys(points)) {
    const n = Number(id.slice(1));
    if (Number.isFinite(n) && n > max) max = n;
  }
  return max;
}

// deterministic, maximally-distinct hues via the golden-angle rotation
// (137.5..deg apart each step never repeats/clusters the way an even
// N-way split would once measurements are added/removed) - "consistent
// unique colors" per measurement, same swatch used for its landmark
// markers, its connecting line, its legend row, and (server-side, see
// api/routers/facial.py's export_batch) its Excel legend cell, since the
// color is computed once here and carried through every request from then
// on (see api/schemas.py's FacialMeasurementDef.color).
const GOLDEN_ANGLE_DEG = 137.508;

export function colorForMeasurement(index) {
  const hue = (index * GOLDEN_ANGLE_DEG) % 360;
  return hslToHex(hue, 70, 55);
}

function hslToHex(h, s, l) {
  const sNorm = s / 100;
  const lNorm = l / 100;
  const c = (1 - Math.abs(2 * lNorm - 1)) * sNorm;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = lNorm - c / 2;
  let r = 0;
  let g = 0;
  let b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const toHex = (v) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// hex string ("#4ade80") -> the numeric form three.js materials expect.
export function colorToThreeHex(hex) {
  return parseInt(hex.replace("#", ""), 16);
}

export const MEASUREMENT_TYPE_LABELS = { linear: "Linear", angular: "Angular", area: "Surface Area" };
export const MEASUREMENT_TYPE_UNITS = { linear: "mm", angular: "deg", area: "mm²" };

// exact/min point count per type - MeasurementForm.jsx's own "Confirm"
// gate; the backend re-validates the same rule (see
// craniumpy_core.facial_measurements.compute_measurement) rather than
// trusting this alone.
export function pointCountValid(type, count) {
  if (type === "linear") return count === 2;
  if (type === "angular") return count === 3;
  if (type === "area") return count >= 3;
  return false;
}

// folds a fresh {measurementId: geometry} response (render_paths or
// render_faces from a preview/correction call) into a previously-held map,
// for exactly the measurement ids that were just recomputed (affectedIds) -
// a measurement absent from `updates` (its surface trace couldn't be
// re-traced, e.g. dragged onto a disconnected part of the mesh) has its
// stale entry explicitly cleared rather than left showing the old geometry,
// the same "only affected measurements change, and they change completely"
// contract handleDrag/handleCorrect already follow for values/valueErrors.
export function mergeRenderGeometry(prev, affectedIds, updates) {
  const next = { ...prev };
  for (const id of affectedIds) {
    if (id in updates) next[id] = updates[id];
    else delete next[id];
  }
  return next;
}

export function pointCountHint(type) {
  if (type === "linear") return "exactly 2 points";
  if (type === "angular") return "exactly 3 points";
  if (type === "area") return "3 or more points, forming a closed boundary";
  return "";
}
