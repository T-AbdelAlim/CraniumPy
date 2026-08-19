import { useEffect, useState } from "react";
import UploadPanel from "../data/UploadPanel.jsx";
import Viewer from "../../components/Viewer.jsx";
import { meshUrl, startAlign, startClip, pollStatus } from "../../api/sessions.js";
import { measureMesh } from "../../api/longitudinal.js";
import { LANDMARK_COLORS, LANDMARK_LABELS, LANDMARK_NAMES, nextUnpickedLandmark } from "../../lib/landmarks.js";

// one compared image's own mini pipeline + its own <Viewer> - deliberately a
// smaller state machine than App.jsx's own (no target-switch snapshotting,
// no alt-frontal landmark, no save/export UI - those stay Patients-only).
// two ways to get a mesh ready for comparison:
//   "pipeline" - upload a raw scan, pick 3 landmarks, register + clip (no
//     separate "Run"/resample step - see the module comment below for why).
//   "preregistered" - point at a file that's already the OUTPUT of a prior
//     Patients session (an _rg/_rg_C/_rg_F/_rg_{C|F}N.ply) - it's already in
//     this app's canonical registered frame, so it's usable immediately, no
//     landmark picking needed (see api/schemas.py's
//     LongitudinalMeshRef.stage="original").
//
// neither path ever calls /run: craniumpy_core.cohort.measure_mean_shape
// (exposed here as api/longitudinal.js's measureMesh) computes the full
// craniometrics/asymmetry/metopic/frontal_bossing suite directly on an
// already-registered mesh, assuming the fixed reference-triangle frame
// every registered mesh in this app shares - the same trick the Cohort
// workspace's mean-shape measurements already rely on. that sidesteps
// needing a session's own /run (built for the single-patient
// upload->align->clip->run flow's resample+measure step) entirely.
export default function TimepointSlot({ slot, onChange, viewerRef, colorIndex, canRemove, onRemove }) {
  const [entryMode, setEntryMode] = useState(null); // null | "pipeline" | "preregistered"
  const [target, setTarget] = useState("cranium");
  const [sessionId, setSessionId] = useState(null);
  const [landmarks, setLandmarks] = useState({});
  const [stage, setStage] = useState("upload"); // "upload" | "picking" | "processing" | "ready"
  const [status, setStatus] = useState("");
  const [meshStage, setMeshStage] = useState("original");
  const [measurements, setMeasurements] = useState(null);

  const displayLandmarks = {};
  for (const [name, p] of Object.entries(landmarks)) displayLandmarks[name] = p;

  // reflects the mesh currently in the viewer whenever sessionId/meshStage
  // changes - landmark markers stay controlled by the `landmarks` prop
  // regardless (Viewer.jsx re-syncs them independently of displayMesh).
  useEffect(() => {
    if (!sessionId || !viewerRef.current) return;
    viewerRef.current.displayMesh(meshUrl(sessionId, meshStage), { selectionHasTexture: false });
  }, [sessionId, meshStage]);

  // sid is always passed explicitly rather than read from the sessionId
  // state - handleUploaded needs to call this in the very same tick as
  // setSessionId(sid), before that state update has actually landed (React
  // state isn't synchronous), so reading the `sessionId` closure variable
  // there would still see the PREVIOUS value (null, for a fresh slot).
  async function measureAndReport(sid, stageForRef) {
    setStatus("measuring...");
    try {
      const m = await measureMesh({ sessionId: sid, stage: stageForRef }, target);
      setMeasurements(m);
      setStage("ready");
      setStatus("");
      onChange({
        ...slot, sessionId: sid, stage: stageForRef, target, measurements: m, ready: true,
      });
    } catch (err) {
      setStatus(`measurement failed: ${err.message}`);
    }
  }

  function handleUploaded({ sessionId: sid }) {
    setSessionId(sid);
    if (entryMode === "preregistered") {
      setMeshStage("original");
      measureAndReport(sid, "original");
    } else {
      setStage("picking");
      setStatus("ctrl/cmd-click the mesh to place each landmark");
    }
  }

  function handlePick(point) {
    setLandmarks((prev) => {
      const name = nextUnpickedLandmark(prev, false);
      return name ? { ...prev, [name]: point } : prev;
    });
  }

  function handleDrag(name, point) {
    setLandmarks((prev) => ({ ...prev, [name]: point }));
  }

  async function handleRegister() {
    setStage("processing");
    setStatus("registering...");
    try {
      const body = { target, landmarks: LANDMARK_NAMES.map((n) => landmarks[n]) };
      await startAlign(sessionId, body);
      await pollStatus(sessionId, (s, detail) => setStatus(detail ? `${s}: ${detail}` : s));
      setStatus("clipping...");
      await startClip(sessionId, { target, landmarks: LANDMARK_NAMES.map((n) => landmarks[n]), comTranslation: true });
      await pollStatus(sessionId, (s, detail) => setStatus(detail ? `${s}: ${detail}` : s));
      setMeshStage("clipped");
      // landmarks were picked in the RAW mesh's own coordinates - once the
      // viewer switches to showing the clipped/registered mesh, those
      // points no longer correspond to anything on screen (and the pick
      // handler is gone anyway, see the Viewer's onPick prop below), so
      // there's nothing for the markers to still be pointing at.
      setLandmarks({});
      await measureAndReport(sessionId, "clipped");
    } catch (err) {
      setStatus(`registration failed: ${err.message}`);
      setStage("picking");
    }
  }

  function handleReset() {
    setEntryMode(null);
    setSessionId(null);
    setLandmarks({});
    setStage("upload");
    setStatus("");
    setMeasurements(null);
    onChange({ ...slot, sessionId: null, ready: false, measurements: null });
  }

  const pickedCount = LANDMARK_NAMES.filter((n) => n in landmarks).length;
  const nextLandmark = nextUnpickedLandmark(landmarks, false);

  return (
    <div className="longitudinal-slot">
      <div className="longitudinal-slot-header">
        <span className="longitudinal-slot-swatch" style={{ background: slot.color }} />
        <input
          type="text"
          className="longitudinal-slot-label-input"
          value={slot.label}
          placeholder={`Timepoint ${colorIndex + 1}`}
          onChange={(e) => onChange({ ...slot, label: e.target.value })}
        />
        {canRemove && (
          <button type="button" className="button-subtle longitudinal-slot-remove" onClick={onRemove}>
            remove
          </button>
        )}
      </div>

      <div className="longitudinal-slot-viewer">
        <Viewer
          ref={viewerRef}
          wireframe={false}
          textureEnabled={false}
          landmarks={displayLandmarks}
          landmarkColors={LANDMARK_COLORS}
          onPick={stage === "picking" ? handlePick : undefined}
          onDrag={stage === "picking" ? handleDrag : undefined}
        />
      </div>

      <div className="longitudinal-slot-controls">
        {entryMode === null && (
          <>
            <div className="longitudinal-slot-target">
              <label>
                <input type="radio" checked={target === "cranium"} onChange={() => setTarget("cranium")} /> cranium
              </label>
              <label>
                <input type="radio" checked={target === "face"} onChange={() => setTarget("face")} /> face
              </label>
            </div>
            <button type="button" onClick={() => setEntryMode("pipeline")}>
              new scan (upload + register)
            </button>
            <button type="button" className="button-subtle" onClick={() => setEntryMode("preregistered")}>
              already registered file...
            </button>
          </>
        )}

        {entryMode !== null && stage === "upload" && (
          <>
            <p className="hint">
              {entryMode === "preregistered"
                ? "pick an already-registered mesh (an _rg/_rg_C/_rg_F file this app exported before) - used as-is, no landmark picking needed."
                : "pick the raw scan for this timepoint."}
            </p>
            <UploadPanel onUploaded={handleUploaded} />
            <button type="button" className="button-subtle" onClick={() => setEntryMode(null)}>
              back
            </button>
          </>
        )}

        {stage === "picking" && (
          <>
            <p className="status-line">
              {nextLandmark
                ? `next: ${LANDMARK_LABELS[nextLandmark]} (${pickedCount}/3 placed)`
                : "all 3 landmarks placed - alt/cmd-drag a marker to adjust"}
            </p>
            <button type="button" onClick={handleRegister} disabled={pickedCount < 3}>
              register &amp; clip
            </button>
          </>
        )}

        {(stage === "processing" || (stage === "ready" && status)) && <p className="status-line">{status}</p>}

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
