import { useEffect, useState } from "react";
import Viewer from "../../components/Viewer.jsx";
import MeasurementLegend from "./MeasurementLegend.jsx";
import { facialBatchMeshUrl } from "../../api/facial.js";
import { colorToThreeHex } from "./lib/points.js";

// review, one file at a time - a single active Viewer (never one per file;
// a batch of 50-200 must never mount more than one full mesh at once, see
// api/routers/facial.py's own module docstring), prev/next navigation.
// alt-drag corrects a landmark for the CURRENTLY shown file only (see
// FacialWorkspace.jsx's onCorrect, which calls /batch/{id}/correct and
// only that one file's own stored result changes) - no ctrl-click here,
// since review corrects the measurements already confirmed in Define, it
// never adds new ones.
export default function BatchReviewPanel({ viewerRef, batchId, results, activeIndex, onActiveIndexChange, measurements, onCorrect }) {
  const [loadStatus, setLoadStatus] = useState("");
  const active = results[activeIndex];

  // sequential display-then-nothing-else, same "mesh must actually be on
  // screen before anything reads its state" discipline
  // TimepointSlot.jsx's own mount effect follows - landmark points/values
  // here come straight from the already-computed batch result, not a
  // fresh measure call, so there's no second step to race against.
  useEffect(() => {
    if (!active || active.status !== "ok") return;
    let cancelled = false;
    (async () => {
      setLoadStatus("loading...");
      try {
        await viewerRef.current?.displayMesh(facialBatchMeshUrl(batchId, active.filename), { selectionHasTexture: false });
        if (!cancelled) setLoadStatus("");
      } catch (err) {
        if (!cancelled) setLoadStatus(`failed to load: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, batchId]);

  if (!active) {
    return <p className="hint">No files in this batch.</p>;
  }

  const landmarkColorByPoint = {};
  for (const m of measurements) {
    for (const pid of m.pointIds) {
      if (!(pid in landmarkColorByPoint)) landmarkColorByPoint[pid] = colorToThreeHex(m.color);
    }
  }

  return (
    <div className="facial-batch-review">
      <div className="facial-batch-nav">
        <button type="button" onClick={() => onActiveIndexChange(Math.max(0, activeIndex - 1))} disabled={activeIndex === 0}>
          previous
        </button>
        <span className="hint">
          {activeIndex + 1} / {results.length} - {active.filename}
          {active.status === "error" && " (failed)"}
        </span>
        <button
          type="button"
          onClick={() => onActiveIndexChange(Math.min(results.length - 1, activeIndex + 1))}
          disabled={activeIndex === results.length - 1}
        >
          next
        </button>
      </div>

      {active.status === "error" ? (
        <p className="status-line facial-batch-error">{active.error}</p>
      ) : (
        <>
          <div className="facial-batch-viewer">
            <Viewer
              ref={viewerRef}
              wireframe={false}
              textureEnabled={false}
              landmarks={active.landmarkPoints}
              landmarkColors={landmarkColorByPoint}
              onDrag={(pointId, point) => onCorrect(active.filename, pointId, point)}
            />
            {loadStatus && <p className="hint facial-define-hint">{loadStatus}</p>}
            <p className="hint facial-define-hint">alt-drag a point to correct it for this file only.</p>
          </div>
          <MeasurementLegend measurements={measurements} values={active.values} valueErrors={active.valueErrors} />
        </>
      )}
    </div>
  );
}
