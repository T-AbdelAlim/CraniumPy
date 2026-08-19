import { useEffect, useRef } from "react";
import TimepointSlot from "../TimepointSlot.jsx";
import ComparisonLegend from "../ComparisonLegend.jsx";
import MeasurementComparisonTable from "../MeasurementComparisonTable.jsx";
import { useLinkedCameras } from "../lib/useLinkedCameras.js";
import { measurementsColors, metopicColors, frontalBossingColors } from "../lib/colors.js";

// the default view: N (default 2) side-by-side viewers, each running its own
// TimepointSlot pipeline, with an optional camera link and each slot's own
// measurements/metopic/frontal-bossing overlay drawn in its own
// legend-matched color (see lib/colors.js) - "visualize the extracted
// metrics on top of one another" as linked, color-consistent side-by-side
// viewers rather than one literal shared 3D scene (see this feature's own
// planning notes for why: Viewer.jsx is built around exactly one mesh per
// instance, so a true single-scene overlay would need new multi-mesh scene
// management - this reuses the existing, proven Viewer unchanged).
export default function CompareTab({ slots, onSlotsChange, linkCameras, onLinkCamerasChange, overlayMode, onOverlayModeChange }) {
  // one ref per mounted slot - plain objects (not React.createRef) are fine
  // since these never trigger a render themselves, same convention
  // Viewer.jsx's own internal refs already use.
  const viewerRefsContainer = useRef([]);
  while (viewerRefsContainer.current.length < slots.length) {
    viewerRefsContainer.current.push({ current: null });
  }
  viewerRefsContainer.current.length = slots.length;

  useLinkedCameras(viewerRefsContainer.current, linkCameras);

  useEffect(() => {
    slots.forEach((slot, i) => {
      const viewer = viewerRefsContainer.current[i]?.current;
      if (!viewer || !slot.ready || !slot.measurements) return;
      viewer.hideMeasurementsOverlay();
      viewer.hideMetopicOverlay();
      viewer.hideFrontalBossingOverlay();
      viewer.hideHeatmap();
      if (overlayMode === "none") return;

      const m = slot.measurements;
      if (overlayMode === "asymmetry") {
        viewer.showHeatmap(m.asymmetry.heatmap);
        return;
      }
      if (m.craniometrics) {
        viewer.showMeasurementsOverlay({
          hcPolygon: m.craniometrics.hc_slice_polygon,
          frontOpt: m.craniometrics.front_opt,
          occOpt: m.craniometrics.occ_opt,
          lhOpt: m.craniometrics.lh_opt,
          rhOpt: m.craniometrics.rh_opt,
          colors: measurementsColors(i),
        });
      }
      if (m.metopic) viewer.showMetopicOverlay(m.metopic, metopicColors(i));
      if (m.frontal_bossing) viewer.showFrontalBossingOverlay(m.frontal_bossing, frontalBossingColors(i));
    });
  }, [slots, overlayMode]);

  function updateSlot(index, patch) {
    onSlotsChange(slots.map((s, i) => (i === index ? patch : s)));
  }

  function removeLastSlot() {
    onSlotsChange(slots.slice(0, -1));
  }

  return (
    <div className="longitudinal-compare-tab">
      <div className="longitudinal-toolbar">
        <label>
          <input type="checkbox" checked={linkCameras} onChange={(e) => onLinkCamerasChange(e.target.checked)} />
          link cameras
        </label>
        <label>
          overlay:{" "}
          <select value={overlayMode} onChange={(e) => onOverlayModeChange(e.target.value)}>
            <option value="measurements">measurements</option>
            <option value="asymmetry">asymmetry heatmap</option>
            <option value="none">none</option>
          </select>
        </label>
      </div>

      <div className="longitudinal-grid" style={{ gridTemplateColumns: `repeat(${slots.length}, 1fr)` }}>
        {slots.map((slot, i) => (
          <TimepointSlot
            key={slot.id}
            slot={slot}
            onChange={(patch) => updateSlot(i, patch)}
            viewerRef={viewerRefsContainer.current[i]}
            colorIndex={i}
            canRemove={slots.length > 2 && i === slots.length - 1}
            onRemove={removeLastSlot}
          />
        ))}
      </div>

      <ComparisonLegend slots={slots} />
      <MeasurementComparisonTable slots={slots} />
    </div>
  );
}
