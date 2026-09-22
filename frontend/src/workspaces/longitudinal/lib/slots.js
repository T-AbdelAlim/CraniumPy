import { slotColor } from "./colors.js";

export const MAX_SLOTS = 6; // matches colors.js's palette length - past this, slot colors start repeating

export function makeEmptySlot(index) {
  return {
    id: crypto.randomUUID(),
    label: "",
    color: slotColor(index).swatch,
    sessionId: null,
    stage: null,
    target: "cranium",
    measurements: null,
    ready: false,
  };
}

// merges App.jsx's stagedLongitudinalMeshes ({sessionId, target, stage,
// timepoint, label}) onto baseSlots, one slot PER staged timepoint index
// (parsed from "t0".."t5") - positional, so staging t0 and t2 leaves
// whatever's at slot 1 untouched rather than compacting them together
// (matches PreprocessingPanel.jsx's own "select a timepoint" framing: the
// number picked there is where it lands). two staged meshes for the SAME
// timepoint (a cranium and a face, say) can't both occupy one slot - the
// most recently staged one wins, same "last write wins" resolution
// App.jsx's own array just naturally gives by iteration order.
//
// baseSlots is [] for LongitudinalWorkspace.jsx's own from-scratch mount
// case (falls back to the plain two-empty-slots default when nothing was
// staged either); an EXISTING snapshot's own slots array for App.jsx's
// handleAppModeChange, which merges freshly staged timepoints onto
// whatever the workspace already held (added/replaced timepoints from a
// previous visit) instead of discarding it for a "start from the staged
// mesh(es) or start clean?" prompt - see that call site's own comment.
export function mergeStagedMeshesIntoSlots(baseSlots, stagedMeshes) {
  if (!stagedMeshes || stagedMeshes.length === 0) {
    return baseSlots.length > 0 ? baseSlots : [makeEmptySlot(0), makeEmptySlot(1)];
  }
  const byTimepoint = new Map();
  for (const m of stagedMeshes) {
    const index = Number(String(m.timepoint).replace("t", "")) || 0;
    byTimepoint.set(index, m);
  }
  const count = Math.min(Math.max(Math.max(...byTimepoint.keys()) + 1, baseSlots.length, 2), MAX_SLOTS);
  return Array.from({ length: count }, (_, i) => {
    const staged = byTimepoint.get(i);
    if (!staged) return baseSlots[i] ?? makeEmptySlot(i);
    return {
      id: crypto.randomUUID(),
      label: staged.label || "",
      color: slotColor(i).swatch,
      sessionId: staged.sessionId,
      stage: staged.stage,
      target: staged.target,
      measurements: null,
      ready: false,
    };
  });
}
