import { useEffect, useRef, useState } from "react";
import TimepointSlot from "../TimepointSlot.jsx";
import ComparisonLegend from "../ComparisonLegend.jsx";
import MeasurementComparisonTable from "../MeasurementComparisonTable.jsx";
import { useLinkedCameras } from "../lib/useLinkedCameras.js";
import { measurementsColors, metopicColors, frontalBossingColors } from "../lib/colors.js";
import { computeDistanceHeatmaps } from "../lib/distanceHeatmap.js";
import { slotStageRef, slotLabel } from "../lib/meshRef.js";
import { fetchShippedTemplates } from "../../../api/sessions.js";

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

  // "distance heatmap" - a per-vertex diff against a reference, distinct
  // from the "asymmetry" heatmap (which compares each mesh's own left/right
  // halves, no cross-timepoint reference at all). three ways to pick that
  // reference - see lib/distanceHeatmap.js's own comment for why this is
  // just a thin wrapper over /api/longitudinal/diff, computed once here
  // (not per render, not per frame) whenever the mode/reference or the
  // ready slots themselves change.
  const [distanceMode, setDistanceMode] = useState("fixed"); // "fixed" | "longitudinal" | "template"
  const [distanceReferenceIndex, setDistanceReferenceIndex] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [distanceTemplate, setDistanceTemplate] = useState("");
  const [distanceHeatmaps, setDistanceHeatmaps] = useState([]); // parallel to slots
  const [distanceStatus, setDistanceStatus] = useState("");

  useLinkedCameras(viewerRefsContainer.current, linkCameras);

  useEffect(() => {
    fetchShippedTemplates()
      .then((list) => {
        setTemplates(list);
        if (list.length > 0) setDistanceTemplate((prev) => prev || list[0].name);
      })
      .catch(() => {});
  }, []);

  const readyIndices = slots.map((s, i) => i).filter((i) => slots[i].ready);

  useEffect(() => {
    if (overlayMode !== "distance" || readyIndices.length < 2) {
      setDistanceHeatmaps([]);
      return undefined;
    }
    if (distanceMode === "template" && !distanceTemplate) return undefined;
    let cancelled = false;
    setDistanceStatus("computing...");
    const stages = slots.map((s) => ({ ref: slotStageRef(s) }));
    // readyIndices maps distanceHeatmaps' own positions back onto slots -
    // computeDistanceHeatmaps only ever sees the READY stages (an
    // unfinished slot has no mesh to diff against anything), reference
    // index translated the same way.
    const readyStages = readyIndices.map((i) => stages[i]);
    const referenceReadyIndex = readyIndices.indexOf(distanceReferenceIndex);
    const option = distanceMode === "fixed" ? (referenceReadyIndex >= 0 ? referenceReadyIndex : 0) : distanceTemplate;
    computeDistanceHeatmaps(readyStages, distanceMode, option)
      .then((heatmaps) => {
        if (cancelled) return;
        const bySlotIndex = new Array(slots.length).fill(null);
        readyIndices.forEach((slotIndex, readyPos) => {
          bySlotIndex[slotIndex] = heatmaps[readyPos];
        });
        setDistanceHeatmaps(bySlotIndex);
        setDistanceStatus("");
      })
      .catch((err) => {
        if (!cancelled) setDistanceStatus(`distance heatmap failed: ${err.message}`);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayMode, distanceMode, distanceReferenceIndex, distanceTemplate, JSON.stringify(readyIndices)]);

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
        viewer.showHeatmap(m.asymmetry.heatmap, { dim: false });
        return;
      }
      if (overlayMode === "distance") {
        const heatmap = distanceHeatmaps[i];
        if (heatmap) viewer.showHeatmap(heatmap, { dim: false });
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
  }, [slots, overlayMode, distanceHeatmaps]);

  // functional update, not `onSlotsChange(slots.map(...))` - multiple
  // TimepointSlots auto-measure in parallel on mount (every staged slot's
  // own effect fires independently, nothing sequences them), so two
  // onChange calls can land in the same tick. computing the next array from
  // the closed-over `slots` snapshot means whichever call resolves second
  // overwrites the first's patch with stale data - a lost update where one
  // slot's `ready: true` silently reverts. passing an updater function
  // straight through to setSlots (onSlotsChange IS setSlots, see
  // LongitudinalWorkspace.jsx) makes each patch apply against the true
  // latest state instead.
  function updateSlot(index, patch) {
    onSlotsChange((prev) => prev.map((s, i) => (i === index ? patch : s)));
  }

  function removeLastSlot() {
    onSlotsChange((prev) => prev.slice(0, -1));
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
            <option value="distance">distance heatmap</option>
            <option value="none">none</option>
          </select>
        </label>
        {overlayMode === "distance" && (
          <>
            <label>
              <input type="radio" checked={distanceMode === "fixed"} onChange={() => setDistanceMode("fixed")} />
              reference:{" "}
              <select
                disabled={distanceMode !== "fixed"}
                value={distanceReferenceIndex}
                onChange={(e) => setDistanceReferenceIndex(Number(e.target.value))}
              >
                {slots.map((s, i) => (
                  <option key={s.id} value={i}>
                    {slotLabel(s, i)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input type="radio" checked={distanceMode === "longitudinal"} onChange={() => setDistanceMode("longitudinal")} />
              longitudinal timing (each vs. previous)
            </label>
            <label>
              <input type="radio" checked={distanceMode === "template"} onChange={() => setDistanceMode("template")} />
              custom template:{" "}
              <select disabled={distanceMode !== "template"} value={distanceTemplate} onChange={(e) => setDistanceTemplate(e.target.value)}>
                {templates.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>
      {distanceStatus && <p className="status-line">{distanceStatus}</p>}

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
