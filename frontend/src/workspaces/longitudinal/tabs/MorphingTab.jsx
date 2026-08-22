import { useEffect, useRef, useState } from "react";
import { fetchShippedTemplates } from "../../../api/sessions.js";
import LongitudinalMorphViewer from "../LongitudinalMorphViewer.jsx";
import MorphControl from "../MorphControl.jsx";
import { computeDistanceHeatmaps } from "../lib/distanceHeatmap.js";
import { resampleStageOverlays } from "../lib/overlayMorph.js";
import { slotStageRef, slotLabel, stageMeshUrl } from "../lib/meshRef.js";

// replaces the old "Correspondence" tab entirely - there's nothing left to
// establish. every ready slot is already NICP-fit to a shared template
// before it's ever ready (staged from Preprocessing, or loaded as an
// already-fit file - see TimepointSlot.jsx), so any two of them already
// share point correspondence by construction. this tab is now purely
// visualization: pick which ready timepoints to include, pick an overlay
// (the same three modes Compare tab has, animated here instead of static),
// and play/scrub/export the morph.
//
// ONE large viewer, not a side-by-side pair sharing a CSS grid row with
// anything else - that sharing was the actual cause of the old panel's
// "canvas resizes mid-morph, exported video comes out corrupted" bug: a
// sibling panel's own content changing width mid-playback (heatmap
// checkbox, filenames of different lengths) shifted the grid's own column
// widths, which resized the WebGL canvas underneath the running animation.
// captureStream's video track expects a CONSTANT resolution for its whole
// recording - a canvas that resizes mid-stream is exactly what produced the
// corrupted export. giving this viewer its own fixed-width, nothing-else-
// sharing-the-row container removes the resize trigger entirely.
export default function MorphingTab({ slots }) {
  const readyIndices = slots.map((s, i) => i).filter((i) => slots[i].ready);

  // null = "auto: every ready slot, always" (reactive to slots becoming
  // ready) - the moment the user unchecks/rechecks anything, this becomes
  // an explicit set and stops auto-following new ready slots (ordinary
  // checkbox-group expectations: a manual choice shouldn't get silently
  // overridden by something else finishing later).
  const [manualSelection, setManualSelection] = useState(null);
  const [overlayMode, setOverlayMode] = useState("measurements"); // "measurements" | "asymmetry" | "distance" | "none"
  const [distanceMode, setDistanceMode] = useState("fixed"); // "fixed" | "longitudinal" | "template"
  const [distanceReferenceIndex, setDistanceReferenceIndex] = useState(readyIndices[0] ?? 0);
  const [templates, setTemplates] = useState([]);
  const [distanceTemplate, setDistanceTemplate] = useState("");
  const [status, setStatus] = useState("");

  const morphViewerRef = useRef(null);
  const loadedKeyRef = useRef(null);
  const loadPromiseRef = useRef(null);
  // fullscreens the WHOLE tab (toolbars + MorphControl + canvas together),
  // not just the canvas - see MorphControl.jsx's own handleToggleFullscreen
  // comment for why fullscreen used to hide every control including its
  // own exit button.
  const fullscreenRef = useRef(null);

  useEffect(() => {
    fetchShippedTemplates()
      .then((list) => {
        setTemplates(list);
        if (list.length > 0) setDistanceTemplate((prev) => prev || list[0].name);
      })
      .catch(() => {});
  }, []);

  const selectedIndices = manualSelection ?? new Set(readyIndices);

  function toggleStage(i) {
    setManualSelection((prev) => {
      const base = new Set(prev ?? readyIndices);
      if (base.has(i)) base.delete(i);
      else base.add(i);
      return base;
    });
  }

  const orderedStages = [...selectedIndices]
    .filter((i) => slots[i]?.ready)
    .sort((a, b) => a - b)
    .map((i) => ({ index: i, slot: slots[i] }));
  const sequenceKey = orderedStages.map((s) => `${s.slot.sessionId}:${s.slot.stage}`).join(",");

  // loads the mesh sequence into the viewer exactly once per distinct
  // sequenceKey - memoized via loadedKeyRef/loadPromiseRef so re-running
  // this for an unrelated reason (overlay mode changing, below) is a cheap
  // no-op instead of a real reload. "never reload older meshes unless the
  // user removes or starts over" - changing which stages are SELECTED (via
  // toggleStage) is the only thing that changes sequenceKey.
  function ensureSequenceLoaded(key, urls) {
    if (loadedKeyRef.current === key && loadPromiseRef.current) return loadPromiseRef.current;
    loadedKeyRef.current = key;
    loadPromiseRef.current = morphViewerRef.current.loadSequence(urls);
    return loadPromiseRef.current;
  }

  useEffect(() => {
    if (orderedStages.length < 2) return undefined;
    let cancelled = false;
    (async () => {
      try {
        setStatus("loading sequence...");
        const urls = orderedStages.map((s) => stageMeshUrl(s.slot.sessionId, s.slot.stage));
        await ensureSequenceLoaded(sequenceKey, urls);
        if (!cancelled) setStatus("");
      } catch (err) {
        if (!cancelled) setStatus(`failed to load sequence: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequenceKey]);

  // applies whichever overlay is currently picked - always waits on the
  // (memoized, usually already-resolved) sequence load first, same
  // "mesh has to actually be there before touching its overlay" reasoning
  // every other viewer in this workspace already follows.
  useEffect(() => {
    if (orderedStages.length < 2) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const urls = orderedStages.map((s) => stageMeshUrl(s.slot.sessionId, s.slot.stage));
        await ensureSequenceLoaded(sequenceKey, urls);
        if (cancelled) return;
        const viewer = morphViewerRef.current;
        if (!viewer) return;

        if (overlayMode === "none") {
          viewer.hideHeatmap();
          viewer.hideOverlaySequence();
          return;
        }
        if (overlayMode === "asymmetry") {
          viewer.hideOverlaySequence();
          viewer.showHeatmapSequence(orderedStages.map((s) => s.slot.measurements?.asymmetry?.heatmap ?? null));
          return;
        }
        if (overlayMode === "distance") {
          viewer.hideOverlaySequence();
          if (distanceMode === "template" && !distanceTemplate) return;
          setStatus("computing distance heatmap...");
          const stages = orderedStages.map((s) => ({ ref: slotStageRef(s.slot) }));
          const referencePos = orderedStages.findIndex((s) => s.index === distanceReferenceIndex);
          const option = distanceMode === "fixed" ? (referencePos >= 0 ? referencePos : 0) : distanceTemplate;
          const heatmaps = await computeDistanceHeatmaps(stages, distanceMode, option);
          if (cancelled) return;
          viewer.showHeatmapSequence(heatmaps);
          setStatus("");
          return;
        }
        if (overlayMode === "measurements") {
          viewer.hideHeatmap();
          viewer.showOverlaySequence(orderedStages.map((s) => resampleStageOverlays(s.slot.measurements)));
        }
      } catch (err) {
        if (!cancelled) setStatus(`overlay failed: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequenceKey, overlayMode, distanceMode, distanceReferenceIndex, distanceTemplate]);

  if (readyIndices.length < 2) {
    return <p className="hint">Register at least two timepoints in the Compare tab to morph between them.</p>;
  }

  return (
    <div ref={fullscreenRef} className="longitudinal-morphing-tab">
      <div className="longitudinal-toolbar">
        <span className="hint">timepoints:</span>
        {readyIndices.map((i) => (
          <label key={slots[i].id}>
            <input type="checkbox" checked={selectedIndices.has(i)} onChange={() => toggleStage(i)} />
            {slotLabel(slots[i], i)}
          </label>
        ))}
      </div>
      <div className="longitudinal-toolbar">
        <label>
          overlay:{" "}
          <select value={overlayMode} onChange={(e) => setOverlayMode(e.target.value)}>
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
                {orderedStages.map((s) => (
                  <option key={s.slot.id} value={s.index}>
                    {slotLabel(s.slot, s.index)}
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
      {status && <p className="status-line">{status}</p>}

      <div className="longitudinal-morphing-viewer">
        <MorphControl onT={(t) => morphViewerRef.current?.setT(t)} morphViewerRef={morphViewerRef} fullscreenRef={fullscreenRef} />
        <div className="longitudinal-morphing-viewer-canvas">
          <LongitudinalMorphViewer ref={morphViewerRef} />
        </div>
      </div>
    </div>
  );
}
