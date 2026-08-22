// shared by CompareTab.jsx (one static heatmap per ready slot) and the 3D
// Morphing tab (lerps between two consecutive stages' own heatmaps across
// each leg, the same way it already lerps mesh vertices and measurement
// overlay points) - both need the exact same thing: "each stage's own
// per-vertex distance (mm) from whatever reference this mode picks", just
// applied to a different set of stages in each caller. every mesh this
// workspace ever loads is already NICP-fit to a shared template (staged
// from Preprocessing, or loaded as an already-fit file - see
// TimepointSlot.jsx), so any two of them are already vertex-correspondent -
// nothing here establishes correspondence, it only computes a diff between
// meshes that already share one.
import { computeLongitudinalDiff } from "../../../api/longitudinal.js";

// stages: array of {ref: {sessionId, stage}} (or any object carrying a
// `ref` - callers pass their own richer shape straight through, only `ref`
// is read here) in the relevant order. mode: "fixed" | "longitudinal" |
// "template". option: for "fixed", the index into `stages` to use as the
// reference; for "template", the shipped template name; ignored for
// "longitudinal". returns an array parallel to `stages` - heatmaps[i] is
// null wherever there's no meaningful reference for that stage (the fixed
// reference's own slot, or stage 0 in "longitudinal" mode, which has no
// predecessor). every diff fires in parallel (each pair is independent of
// every other), not as a serial chain - the point of the whole exercise is
// computing this once, up front, cheaply.
export async function computeDistanceHeatmaps(stages, mode, option) {
  const heatmaps = new Array(stages.length).fill(null);

  if (mode === "fixed") {
    const referenceRef = stages[option]?.ref;
    if (!referenceRef) return heatmaps;
    await Promise.all(
      stages.map(async (s, i) => {
        if (i === option) return;
        const diff = await computeLongitudinalDiff(referenceRef, s.ref);
        heatmaps[i] = diff.heatmap;
      }),
    );
  } else if (mode === "longitudinal") {
    await Promise.all(
      stages.slice(1).map(async (s, idx) => {
        const i = idx + 1;
        const diff = await computeLongitudinalDiff(stages[i - 1].ref, s.ref);
        heatmaps[i] = diff.heatmap;
      }),
    );
  } else if (mode === "template") {
    const referenceRef = { template: option };
    await Promise.all(
      stages.map(async (s, i) => {
        const diff = await computeLongitudinalDiff(referenceRef, s.ref);
        heatmaps[i] = diff.heatmap;
      }),
    );
  }

  return heatmaps;
}
