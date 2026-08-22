import { useEffect, useRef, useState } from "react";
import DefinePanel from "./DefinePanel.jsx";
import BatchPicker from "./BatchPicker.jsx";
import BatchReviewPanel from "./BatchReviewPanel.jsx";
import ExportPanel from "./ExportPanel.jsx";
import {
  correctFacialLandmark,
  facialTemplateMeshUrl,
  loadFacialTemplate,
  pickFacialPoint,
  previewFacialMeasurements,
  startFacialBatch,
} from "../../api/facial.js";
import { colorForMeasurement, colorToThreeHex, nextPointId } from "./lib/points.js";

// 4th top-level workspace alongside Patients/Longitudinal/Cohort (see
// components/shell/Shell.jsx's nav) - define custom point-to-point
// measurements (linear/angular/surface-area) on a template mesh, using the
// exact same ctrl-click/alt-drag landmark interaction the Patients
// workspace already has (Viewer.jsx, entirely unchanged - it's already
// generic over a {name: {x,y,z}} points dict, never fixed to the
// sellion/tragus set lib/landmarks.js hardcodes), then batch-extract them
// across many already-NICP-registered patient meshes with a per-mesh
// review/correction step before exporting. own internal tab strip
// (`workspaces={[]}` passed to Shell), same self-contained pattern
// workspaces/cohort/CohortWorkspace.jsx already established.
//
// both tabs stay mounted (display:none when inactive), same reasoning
// LongitudinalWorkspace.jsx's own Compare/3D-Morphing split already
// documents - switching away and back must not re-load the template or
// re-fetch the batch's current mesh.
export default function FacialWorkspace({ onSnapshotChange, initialSnapshot }) {
  const [templateId, setTemplateId] = useState(initialSnapshot?.templateId ?? null);
  const [templateSource, setTemplateSource] = useState(initialSnapshot?.templateSource ?? "default");
  const [templateStatus, setTemplateStatus] = useState("");
  const [points, setPoints] = useState(initialSnapshot?.points ?? {});
  const [measurements, setMeasurements] = useState(initialSnapshot?.measurements ?? []);
  const [measurementValues, setMeasurementValues] = useState({});
  const [measurementValueErrors, setMeasurementValueErrors] = useState({});
  const [pendingMeasurement, setPendingMeasurement] = useState(null); // {type, pointIds} | null
  const [activeTab, setActiveTab] = useState(initialSnapshot?.activeTab ?? "define");
  const [batchId, setBatchId] = useState(initialSnapshot?.batchId ?? null);
  const [batchResults, setBatchResults] = useState(initialSnapshot?.batchResults ?? []);
  const [activeFileIndex, setActiveFileIndex] = useState(initialSnapshot?.activeFileIndex ?? 0);
  const [batchPickStatus, setBatchPickStatus] = useState("");

  const defineViewerRef = useRef(null);
  const batchViewerRef = useRef(null);
  const dragTokenRef = useRef(0);

  useEffect(() => {
    onSnapshotChange?.({ templateId, templateSource, points, measurements, activeTab, batchId, batchResults, activeFileIndex });
  }, [templateId, templateSource, points, measurements, activeTab, batchId, batchResults, activeFileIndex, onSnapshotChange]);

  // loads a template fresh, clearing every point/measurement/batch that
  // belonged to whatever was loaded before - their vertex indices only
  // mean anything against the template they were picked on.
  async function loadTemplate(opts) {
    setTemplateStatus("loading template...");
    try {
      const { templateId: newId, vertexCount, faceCount } = await loadFacialTemplate(opts);
      setTemplateId(newId);
      setTemplateSource(opts.path ? "custom" : "default");
      await defineViewerRef.current?.displayMesh(facialTemplateMeshUrl(newId), { selectionHasTexture: false });
      setTemplateStatus(`${vertexCount} vertices, ${faceCount} faces`);
      setPoints({});
      setMeasurements([]);
      setMeasurementValues({});
      setMeasurementValueErrors({});
      setPendingMeasurement(null);
      setBatchId(null);
      setBatchResults([]);
      setActiveFileIndex(0);
    } catch (err) {
      setTemplateStatus(`failed to load template: ${err.message}`);
    }
  }

  // mount only: restore a snapshotted template if it's still cached
  // server-side, otherwise (fresh workspace, or the cache evicted it -
  // see api/routers/facial.py's own FIFO caches) load the default.
  // deliberately doesn't call loadTemplate on the restore-success path -
  // that would wipe the very state being restored. measurementValues/
  // valueErrors are deliberately NOT part of the snapshot (recomputable,
  // no need to persist them) - restored measurements need a fresh preview
  // call here to actually show a number instead of sitting at "..." forever.
  useEffect(() => {
    (async () => {
      if (templateId) {
        try {
          await defineViewerRef.current?.displayMesh(facialTemplateMeshUrl(templateId), { selectionHasTexture: false });
          setTemplateStatus("restored from previous session");
          if (measurements.length > 0) {
            try {
              const { values, valueErrors } = await previewFacialMeasurements(templateId, points, measurements);
              setMeasurementValues(values);
              setMeasurementValueErrors(valueErrors);
            } catch (err) {
              setTemplateStatus(`restored, but couldn't refresh values: ${err.message}`);
            }
          }
          return;
        } catch {
          // evicted - fall through to a fresh default load
        }
      }
      await loadTemplate({ shippedName: "template_face" });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleUseDefaultTemplate() {
    loadTemplate({ shippedName: "template_face" });
  }

  function handleLoadCustomTemplate(path, errorMsg) {
    if (errorMsg) {
      setTemplateStatus(errorMsg);
      return;
    }
    if (path) loadTemplate({ path });
  }

  async function handlePick(rawPoint) {
    if (activeTab !== "define" || !pendingMeasurement || !templateId) return;
    const required = pendingMeasurement.type === "linear" ? 2 : pendingMeasurement.type === "angular" ? 3 : Infinity;
    if (pendingMeasurement.pointIds.length >= required) return;
    try {
      const { point: snapped } = await pickFacialPoint(templateId, rawPoint);
      const id = nextPointId(Object.keys(points));
      setPoints((prev) => ({ ...prev, [id]: snapped }));
      setPendingMeasurement((prev) => (prev ? { ...prev, pointIds: [...prev.pointIds, id] } : prev));
    } catch (err) {
      setTemplateStatus(`pick failed: ${err.message}`);
    }
  }

  // token-guarded against out-of-order responses (same reasoning
  // Viewer.jsx's own showTemplateOverlay call uses) - a fast drag gesture
  // can fire several of these before the first one's response returns;
  // only the LATEST is ever applied.
  async function handleDrag(pointId, point) {
    setPoints((prev) => ({ ...prev, [pointId]: point }));
    const affected = measurements.filter((m) => m.pointIds.includes(pointId));
    if (affected.length === 0 || !templateId) return;
    const token = ++dragTokenRef.current;
    try {
      const nextPoints = { ...points, [pointId]: point };
      const { values, valueErrors } = await previewFacialMeasurements(templateId, nextPoints, affected);
      if (token !== dragTokenRef.current) return;
      setMeasurementValues((prev) => ({ ...prev, ...values }));
      setMeasurementValueErrors((prev) => ({ ...prev, ...valueErrors }));
    } catch (err) {
      if (token === dragTokenRef.current) setTemplateStatus(`update failed: ${err.message}`);
    }
  }

  function handleStartType(type) {
    setPendingMeasurement({ type, pointIds: [] });
  }

  function handleCancelPending() {
    if (pendingMeasurement) {
      const idsToRemove = pendingMeasurement.pointIds;
      setPoints((prev) => {
        const next = { ...prev };
        for (const id of idsToRemove) delete next[id];
        return next;
      });
    }
    setPendingMeasurement(null);
  }

  async function handleConfirmMeasurement({ name, abbreviation, geodesic }) {
    if (!pendingMeasurement || !templateId) return;
    const def = {
      id: crypto.randomUUID(),
      name,
      abbreviation,
      type: pendingMeasurement.type,
      pointIds: pendingMeasurement.pointIds,
      geodesic: pendingMeasurement.type === "linear" ? geodesic : false,
      color: colorForMeasurement(measurements.length),
    };
    setMeasurements((prev) => [...prev, def]);
    setPendingMeasurement(null);
    try {
      const { values, valueErrors } = await previewFacialMeasurements(templateId, points, [def]);
      setMeasurementValues((prev) => ({ ...prev, ...values }));
      setMeasurementValueErrors((prev) => ({ ...prev, ...valueErrors }));
    } catch (err) {
      setTemplateStatus(`preview failed: ${err.message}`);
    }
  }

  function handleRemoveMeasurement(id) {
    setMeasurements((prev) => prev.filter((m) => m.id !== id));
    setMeasurementValues((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setMeasurementValueErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  // define-phase connecting lines - safe to keep independent of the
  // template's own mesh-load effect (unlike a per-vertex overlay such as
  // showHeatmap, these lines are standalone Three.js objects at absolute
  // point positions, not something that reads the currently-loaded mesh's
  // own geometry, so there's no "drawn before the mesh is ready" race to
  // sequence around).
  useEffect(() => {
    if (!defineViewerRef.current) return;
    const displayMeasurements = pendingMeasurement
      ? [...measurements, { pointIds: pendingMeasurement.pointIds, type: pendingMeasurement.type, color: colorForMeasurement(measurements.length) }]
      : measurements;
    const segments = displayMeasurements
      .map((m) => ({
        points: m.pointIds.map((pid) => points[pid]).filter(Boolean),
        color: colorToThreeHex(m.color),
        closed: m.type === "area",
      }))
      .filter((seg) => seg.points.length >= 2);
    defineViewerRef.current.showFacialMeasurementLines(segments);
  }, [measurements, points, pendingMeasurement]);

  // batch-review connecting lines - same reasoning, driven by the active
  // file's own already-fetched landmark points.
  useEffect(() => {
    if (!batchViewerRef.current) return;
    const active = batchResults[activeFileIndex];
    if (!active || active.status !== "ok") {
      batchViewerRef.current.hideFacialMeasurementLines();
      return;
    }
    const segments = measurements
      .map((m) => ({
        points: m.pointIds.map((pid) => active.landmarkPoints[pid]).filter(Boolean),
        color: colorToThreeHex(m.color),
        closed: m.type === "area",
      }))
      .filter((seg) => seg.points.length >= 2);
    batchViewerRef.current.showFacialMeasurementLines(segments);
  }, [measurements, batchResults, activeFileIndex]);

  async function handlePathsPicked(paths, errorMsg) {
    if (errorMsg) {
      setBatchPickStatus(errorMsg);
      return;
    }
    if (!paths || paths.length === 0 || !templateId) return;
    setBatchPickStatus(`processing ${paths.length} mesh${paths.length === 1 ? "" : "es"}...`);
    try {
      const { batchId: newBatchId, results } = await startFacialBatch(templateId, paths, points, measurements);
      setBatchId(newBatchId);
      setBatchResults(results);
      setActiveFileIndex(0);
      setBatchPickStatus("");
    } catch (err) {
      setBatchPickStatus(`batch failed: ${err.message}`);
    }
  }

  async function handleCorrect(filename, pointId, point) {
    try {
      const { values, valueErrors } = await correctFacialLandmark(batchId, filename, pointId, point);
      setBatchResults((prev) =>
        prev.map((r) => {
          if (r.filename !== filename) return r;
          const nextValueErrors = { ...r.valueErrors };
          for (const mid of Object.keys(values)) {
            if (valueErrors[mid]) nextValueErrors[mid] = valueErrors[mid];
            else delete nextValueErrors[mid];
          }
          return { ...r, landmarkPoints: { ...r.landmarkPoints, [pointId]: point }, values: { ...r.values, ...values }, valueErrors: nextValueErrors };
        }),
      );
    } catch (err) {
      setBatchPickStatus(`correction failed: ${err.message}`);
    }
  }

  const landmarkColorByPoint = {};
  for (const m of measurements) {
    for (const pid of m.pointIds) if (!(pid in landmarkColorByPoint)) landmarkColorByPoint[pid] = colorToThreeHex(m.color);
  }
  if (pendingMeasurement) {
    const pendingColor = colorToThreeHex(colorForMeasurement(measurements.length));
    for (const pid of pendingMeasurement.pointIds) if (!(pid in landmarkColorByPoint)) landmarkColorByPoint[pid] = pendingColor;
  }

  const okCount = batchResults.filter((r) => r.status === "ok").length;

  return (
    <div className="facial-ws">
      <div className="facial-ws-tabs">
        <button type="button" className={activeTab === "define" ? "facial-ws-tab active" : "facial-ws-tab"} onClick={() => setActiveTab("define")}>
          Define
        </button>
        <button
          type="button"
          className={activeTab === "batch" ? "facial-ws-tab active" : "facial-ws-tab"}
          onClick={() => setActiveTab("batch")}
          disabled={measurements.length === 0}
        >
          Batch
        </button>
      </div>
      <div className="facial-ws-content">
        <div style={{ display: activeTab === "define" ? undefined : "none" }}>
          <DefinePanel
            viewerRef={defineViewerRef}
            points={points}
            landmarkColorByPoint={landmarkColorByPoint}
            onPick={handlePick}
            onDrag={handleDrag}
            templateStatus={templateStatus}
            templateSource={templateSource}
            onLoadCustomTemplate={handleLoadCustomTemplate}
            onUseDefaultTemplate={handleUseDefaultTemplate}
            measurements={measurements}
            measurementValues={measurementValues}
            measurementValueErrors={measurementValueErrors}
            pendingMeasurement={pendingMeasurement}
            onStartType={handleStartType}
            onConfirmMeasurement={handleConfirmMeasurement}
            onCancelPending={handleCancelPending}
            onRemoveMeasurement={handleRemoveMeasurement}
            canProceedToBatch={measurements.length > 0}
            onProceedToBatch={() => setActiveTab("batch")}
          />
        </div>
        <div style={{ display: activeTab === "batch" ? undefined : "none" }}>
          {batchId ? (
            <>
              <BatchReviewPanel
                viewerRef={batchViewerRef}
                batchId={batchId}
                results={batchResults}
                activeIndex={activeFileIndex}
                onActiveIndexChange={setActiveFileIndex}
                measurements={measurements}
                onCorrect={handleCorrect}
              />
              <ExportPanel batchId={batchId} resultCount={batchResults.length} okCount={okCount} />
            </>
          ) : (
            <BatchPicker onPathsPicked={handlePathsPicked} status={batchPickStatus} />
          )}
        </div>
      </div>
    </div>
  );
}
