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
export default function LongitudinalWorkspace({ onHasDataChange, initialStagedMeshes }) {
  // lazy initializer - runs once, at mount, matching this component's own
  // full-remount-per-appMode-switch lifecycle (see App.jsx's appMode
  // comment) - initialStagedMeshes changing after mount (it doesn't, in
  // practice, but even if it did) is deliberately NOT reactive here.
  const [slots, setSlots] = useState(() => buildInitialSlots(initialStagedMeshes));
  const [activeTab, setActiveTab] = useState("compare");
  const [linkCameras, setLinkCameras] = useState(true);
  const [overlayMode, setOverlayMode] = useState("measurements");

  // reports "is there anything here that switching away would throw away"
  // up to App.jsx's workspace-switch guard (see its own handleAppModeChange)
  // - any slot that's at least started uploading counts, not just a fully
  // "ready" one, since even a half-finished registration is real in-progress
  // work worth confirming before it's gone.
  useEffect(() => {
    onHasDataChange?.(slots.some((s) => s.sessionId || s.ready));
  }, [slots, onHasDataChange]);

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
