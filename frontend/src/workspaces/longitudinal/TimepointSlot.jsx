import { useEffect, useState } from "react";
import UploadPanel from "../data/UploadPanel.jsx";
import Viewer from "../../components/Viewer.jsx";
import { meshUrl } from "../../api/sessions.js";
import { measureMesh } from "../../api/longitudinal.js";
import { detectNicpTargetFromFilename } from "./lib/detectTarget.js";
import { stageMeshUrl } from "./lib/meshRef.js";

// one compared timepoint's own <Viewer> - deliberately a much smaller state
// machine than App.jsx's own (no landmark picking, no target-switch
// snapshotting, no save/export UI - those stay Patients-only). every mesh
// here is assumed already NICP-fit to a shared template in the Patients
// workspace (POST /{session_id}/run with a NicpConfig.template, or
// "stage for Longitudinal" right after that fit - see
// PreprocessingPanel.jsx) - there's no raw-scan upload or register/clip
// pipeline in this workspace at all anymore, only loading an already-fit
// result.
//
// craniumpy_core.cohort.measure_mean_shape (exposed here as
// api/longitudinal.js's measureMesh) computes the full craniometrics/
// asymmetry/metopic/frontal_bossing suite directly on an already-registered
// mesh, assuming the fixed reference-triangle frame every registered mesh
// in this app shares - the same trick the Cohort workspace's mean-shape
// measurements already rely on. that sidesteps needing a session's own /run
// (built for the single-patient upload->align->clip->run flow's
// resample+measure step) entirely.
//
// viewerRef.current.displayMesh(...) is explicitly awaited, in line, before
// anything that depends on the mesh actually being on screen (measuring, or
// CompareTab's own overlay/heatmap effect noticing slot.ready flip true) -
// this used to be a separate useEffect keyed on [sessionId, meshStage] that
// fired the load WITHOUT awaiting it, racing against measureAndReport's own
// (independent) API call: whichever finished first didn't matter for
// correctness, but if the measurement finished BEFORE the mesh had actually
// loaded, CompareTab's overlay effect ran against a Viewer with nothing (or
// the previous mesh) in it - every show*Overlay/showHeatmap call silently
// no-ops with no mesh to draw on, and nothing ever re-triggers them once the
// mesh finally does load. that was the "asymmetry heatmap shows opaque, no
// color" bug.
export default function TimepointSlot({ slot, onChange, viewerRef, colorIndex, canRemove, onRemove }) {
  const [entryStarted, setEntryStarted] = useState(false);
  // seeded straight from `slot` when it already carries a staged mesh (see
  // LongitudinalWorkspace.jsx's buildInitialSlots) - this instance never
  // shows the "load pre-registered file" UI at all in that case, the mount
  // effect below immediately displays+measures it instead.
  const [target, setTarget] = useState(slot.target || "cranium");
  const [detectedTargetNote, setDetectedTargetNote] = useState(null); // {detected} | null
  const [sessionId, setSessionId] = useState(slot.sessionId);
  const [stage, setStage] = useState(slot.sessionId && !slot.ready ? "processing" : "upload"); // "upload" | "processing" | "ready"
  const [status, setStatus] = useState("");
  const [measurements, setMeasurements] = useState(null);

  // a staged mesh (sessionId already known, but not yet measured/displayed
  // in THIS viewer instance - a fresh TimepointSlot mount never has) -
  // finishes the same displayMesh+measure sequence handleUploaded runs for
  // a manually-picked file, just without any upload step. runs once, at
  // mount only (a staged slot's identity never changes after that - see
  // key={slot.id} in CompareTab.jsx).
  useEffect(() => {
    if (!slot.sessionId || slot.ready) return;
    (async () => {
      await viewerRef.current?.displayMesh(stageMeshUrl(slot.sessionId, slot.stage || "nicp_result"), { selectionHasTexture: false });
      await measureAndReport(slot.sessionId, slot.stage || "nicp_result", slot.target || "cranium");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function measureAndReport(sid, stageForRef, measureTarget) {
    setStage("processing");
    setStatus("measuring...");
    try {
      const m = await measureMesh({ sessionId: sid, stage: stageForRef }, measureTarget);
      setMeasurements(m);
      setStage("ready");
      setStatus("");
      onChange({
        ...slot, sessionId: sid, stage: stageForRef, target: measureTarget, measurements: m, ready: true,
      });
    } catch (err) {
      setStatus(`measurement failed: ${err.message}`);
      setStage("upload");
    }
  }

  async function handleUploaded({ sessionId: sid, meshLabel }) {
    setSessionId(sid);
    const detected = detectNicpTargetFromFilename(meshLabel || "");
    const effectiveTarget = detected || target;
    if (detected && detected !== target) {
      setTarget(detected);
      setDetectedTargetNote({ detected });
    }
    await viewerRef.current?.displayMesh(meshUrl(sid, "original"), { selectionHasTexture: false });
    await measureAndReport(sid, "original", effectiveTarget);
  }

  function handleReset() {
    setEntryStarted(false);
    setSessionId(null);
    setStage("upload");
    setStatus("");
    setMeasurements(null);
    setDetectedTargetNote(null);
    onChange({ ...slot, sessionId: null, ready: false, measurements: null });
  }

  return (
    <div className="longitudinal-slot">
      <div className="longitudinal-slot-header">
        <span className="longitudinal-slot-swatch" style={{ background: slot.color }} />
        <input
          type="text"
          className="longitudinal-slot-label-input"
          value={slot.label}
          placeholder={`Timepoint ${colorIndex}`}
          onChange={(e) => onChange({ ...slot, label: e.target.value })}
        />
        {canRemove && (
          <button type="button" className="button-subtle longitudinal-slot-remove" onClick={onRemove}>
            remove
          </button>
        )}
      </div>

      <div className="longitudinal-slot-viewer">
        <Viewer ref={viewerRef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
      </div>

      <div className="longitudinal-slot-controls">
        {stage === "upload" && !entryStarted && (
          <>
            <div className="longitudinal-slot-target">
              <label>
                <input type="radio" checked={target === "cranium"} onChange={() => setTarget("cranium")} /> cranium
              </label>
              <label>
                <input type="radio" checked={target === "face"} onChange={() => setTarget("face")} /> face
              </label>
            </div>
            <button type="button" onClick={() => setEntryStarted(true)}>
              Load pre-registered (NICP) file...
            </button>
          </>
        )}

        {stage === "upload" && entryStarted && (
          <>
            <p className="hint">
              pick a mesh already NICP-fit to a shared template - an {target === "cranium" ? "_rg_CN.ply" : "_rg_FN.ply"} file
              (from a Preprocessing session's "stage for Longitudinal", or exported/saved the same way).
            </p>
            <UploadPanel onUploaded={handleUploaded} />
            <button type="button" className="button-subtle" onClick={() => setEntryStarted(false)}>
              back
            </button>
          </>
        )}

        {(stage === "processing" || (stage === "ready" && status)) && <p className="status-line">{status}</p>}

        {stage === "ready" && detectedTargetNote && (
          <p className="longitudinal-detected-note">
            recognized {detectedTargetNote.detected === "face" ? "facial" : "cranial"} mesh, switched to "
            {detectedTargetNote.detected === "face" ? "face" : "cranium"}"
            <button
              type="button"
              className="button-subtle"
              onClick={() => {
                const other = target === "face" ? "cranium" : "face";
                setTarget(other);
                setDetectedTargetNote(null);
                measureAndReport(sessionId, "original", other);
              }}
            >
              use {target === "face" ? "cranium" : "face"} instead
            </button>
          </p>
        )}

        {stage === "ready" && (
          <>
            <p className="status-line">
              ready ({target}) - {measurements?.craniometrics ? "craniometrics" : measurements?.metopic ? "metopic" : ""}{" "}
              computed
            </p>
            <button type="button" className="button-subtle" onClick={handleReset}>
              start over
            </button>
          </>
        )}
      </div>
    </div>
  );
}
