import { useEffect, useState } from "react";
import CompareTab from "./tabs/CompareTab.jsx";
import MorphingTab from "./tabs/MorphingTab.jsx";
import { slotColor } from "./lib/colors.js";

const TABS = [
  { id: "compare", label: "Compare" },
  { id: "morphing", label: "3D Morphing" },
];

const MAX_SLOTS = 6; // matches lib/colors.js's palette length - past this, slot colors start repeating

function makeEmptySlot(index) {
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

// converts App.jsx's stagedLongitudinalMeshes ({sessionId, target, stage,
// timepoint, label}) into this workspace's own slot shape, one slot PER
// staged timepoint index (parsed from "t0".."t5") - positional, so staging
// t0 and t2 leaves slot 1 empty rather than compacting them together
// (matches PreprocessingPanel.jsx's own "select a timepoint" framing: the
// number picked there is where it lands). two staged meshes for the SAME
// timepoint (a cranium and a face, say) can't both occupy one slot - the
// most recently staged one wins, same "last write wins" resolution
// App.jsx's own array just naturally gives by iteration order. falls back
// to the plain two-empty-slots default when nothing was staged (or "load
// clean workspace" was picked - see App.jsx's loadStagedIntoLongitudinal).
function buildInitialSlots(stagedMeshes) {
  if (!stagedMeshes || stagedMeshes.length === 0) return [makeEmptySlot(0), makeEmptySlot(1)];
  const byTimepoint = new Map();
  for (const m of stagedMeshes) {
    const index = Number(String(m.timepoint).replace("t", "")) || 0;
    byTimepoint.set(index, m);
  }
  const count = Math.min(Math.max(Math.max(...byTimepoint.keys()) + 1, 2), MAX_SLOTS);
  return Array.from({ length: count }, (_, i) => {
    const staged = byTimepoint.get(i);
    if (!staged) return makeEmptySlot(i);
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

// third top-level workspace alongside Patients/Cohort (see
// components/shell/Shell.jsx's nav) - compares two or more ALREADY NICP-fit
// 3D images of the same patient (side-by-side viewers with linked cameras
// and color-matched measurement overlays, CompareTab), or morphs smoothly
// between them (MorphingTab). no fitting/registration happens in this
// workspace at all - every mesh here already got NICP-fit to a shared
// template in the Patients workspace before it arrives, either staged
// straight from there (see App.jsx's stagedLongitudinalMeshes) or loaded as
// an already-fit file (TimepointSlot.jsx's "Load pre-registered (NICP)
// file..."), so point correspondence across timepoints already exists by
// construction - there's nothing left to establish here. own internal tab
// strip, `workspaces={[]}` passed to Shell - same self-contained pattern
// workspaces/cohort/CohortWorkspace.jsx already established.
//
// owns the slots array here, at the top, since both tabs read the same
// data: CompareTab drives each slot's own load, MorphingTab picks which
// ready slots to include in the morph chain.
export default function LongitudinalWorkspace({ onSnapshotChange, initialStagedMeshes, initialSnapshot }) {
  // lazy initializers - run once, at mount, matching this component's own
  // full-remount-per-appMode-switch lifecycle (see App.jsx's appMode
  // comment) - neither prop changing after mount (they don't, in practice)
  // is deliberately reactive here. initialSnapshot (a preserved
  // {slots, activeTab, linkCameras, overlayMode} from the last time this
  // workspace was left - see App.jsx's longitudinalSnapshot/
  // handleRestorePrevious) takes priority when given; App.jsx never passes
  // both at once (a fresh staging prompt always wins over a passive
  // leftover snapshot), but preferring it here is the safe order either
  // way. a restored slot's own ready/measurements reset to false/null -
  // same "seeded with just {sessionId, stage, target}, re-displayed and
  // re-measured on mount" trick TimepointSlot.jsx already does for a
  // staged slot, reused here instead of trying to resurrect the live
  // Viewer scene/measurement blob itself.
  const [slots, setSlots] = useState(() => {
    if (initialSnapshot) return initialSnapshot.slots.map((s) => ({ ...s, ready: false, measurements: null }));
    return buildInitialSlots(initialStagedMeshes);
  });
  const [activeTab, setActiveTab] = useState(() => initialSnapshot?.activeTab ?? "compare");
  const [linkCameras, setLinkCameras] = useState(() => initialSnapshot?.linkCameras ?? true);
  const [overlayMode, setOverlayMode] = useState(() => initialSnapshot?.overlayMode ?? "measurements");

  // reports this workspace's own lightweight, JSON-safe state up to
  // App.jsx on every change - deliberately dropping measurements/ready
  // (heavy/GPU-recomputable - see the mount initializer above for how a
  // restore reconstructs them), keeping only what's needed to rebuild the
  // scene from scratch.
  useEffect(() => {
    onSnapshotChange?.({
      slots: slots.map(({ id, label, color, sessionId, stage, target }) => ({ id, label, color, sessionId, stage, target })),
      activeTab,
      linkCameras,
      overlayMode,
    });
  }, [slots, activeTab, linkCameras, overlayMode, onSnapshotChange]);

  function handleAddSlot() {
    setSlots((prev) => (prev.length >= MAX_SLOTS ? prev : [...prev, makeEmptySlot(prev.length)]));
  }

  return (
    <div className="longitudinal-ws">
      <div className="longitudinal-ws-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={t.id === activeTab ? "longitudinal-ws-tab active" : "longitudinal-ws-tab"}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
        {activeTab === "compare" && (
          <button
            type="button"
            className="button-subtle longitudinal-ws-add-slot"
            onClick={handleAddSlot}
            disabled={slots.length >= MAX_SLOTS}
          >
            + add timepoint
          </button>
        )}
      </div>
      <div className="longitudinal-ws-content">
        {/* both tabs stay mounted the whole time, just hidden via CSS when
            not active - not a conditional render. each tab owns real,
            hard-to-recompute state (loaded Viewer meshes, the morph
            sequence already loaded into LongitudinalMorphViewer...) that a
            full unmount would throw away - switching back to Compare used
            to come back to an empty upload screen with the meshes gone
            from the viewers, even though the underlying
            sessions/measurements were still perfectly valid. */}
        <div style={{ display: activeTab === "compare" ? undefined : "none" }}>
          <CompareTab
            slots={slots}
            onSlotsChange={setSlots}
            linkCameras={linkCameras}
            onLinkCamerasChange={setLinkCameras}
            overlayMode={overlayMode}
            onOverlayModeChange={setOverlayMode}
          />
        </div>
        <div style={{ display: activeTab === "morphing" ? undefined : "none" }}>
          <MorphingTab slots={slots} />
        </div>
      </div>
    </div>
  );
}
