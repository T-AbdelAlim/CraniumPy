import { useState } from "react";
import CompareTab from "./tabs/CompareTab.jsx";
import CorrespondenceTab from "./tabs/CorrespondenceTab.jsx";
import { slotColor } from "./lib/colors.js";

const TABS = [
  { id: "compare", label: "Compare" },
  { id: "correspondence", label: "Correspondence" },
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

// third top-level workspace alongside Patients/Cohort (see
// components/shell/Shell.jsx's nav) - compares two (by default, extensible
// to more) already-registered 3D images of the same patient, or a patient
// against a reference: side-by-side viewers with linked cameras and
// color-matched measurement overlays (CompareTab), then NICP-based point
// correspondence, a per-vertex change heatmap, and a morph animation
// (CorrespondenceTab). own internal tab strip, `workspaces={[]}` passed to
// Shell - same self-contained pattern workspaces/cohort/CohortWorkspace.jsx
// already established.
//
// owns the slots array here, at the top, since both tabs read the same
// data: CompareTab drives each slot's own upload/register pipeline,
// CorrespondenceTab picks two already-ready slots to fit/diff/morph.
export default function LongitudinalWorkspace() {
  const [slots, setSlots] = useState([makeEmptySlot(0), makeEmptySlot(1)]);
  const [activeTab, setActiveTab] = useState("compare");
  const [linkCameras, setLinkCameras] = useState(true);
  const [overlayMode, setOverlayMode] = useState("measurements");

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
        {activeTab === "compare" && (
          <CompareTab
            slots={slots}
            onSlotsChange={setSlots}
            linkCameras={linkCameras}
            onLinkCamerasChange={setLinkCameras}
            overlayMode={overlayMode}
            onOverlayModeChange={setOverlayMode}
          />
        )}
        {activeTab === "correspondence" && <CorrespondenceTab slots={slots} />}
      </div>
    </div>
  );
}
