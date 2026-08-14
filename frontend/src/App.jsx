import { useRef, useState } from "react";
import Shell from "./components/shell/Shell.jsx";
import Viewer from "./components/Viewer.jsx";
import UploadPanel from "./workspaces/data/UploadPanel.jsx";
import MeshViewToggles from "./workspaces/data/MeshViewToggles.jsx";
import RegisterPanel from "./workspaces/register/RegisterPanel.jsx";
import { meshUrl, startAlign, pollStatus } from "./api/sessions.js";
import { LANDMARK_NAMES, LANDMARK_COLORS, nextUnpickedLandmark } from "./lib/landmarks.js";

const WORKSPACES = [
  { id: "data", label: "Data" },
  { id: "register", label: "Register" },
];

function App() {
  const viewerRef = useRef(null);
  const [sessionId, setSessionId] = useState(null);
  const [meshLabel, setMeshLabel] = useState("");
  const [selectionHasTexture, setSelectionHasTexture] = useState(false);
  const [wireframe, setWireframe] = useState(false);
  const [textureEnabled, setTextureEnabled] = useState(false);
  const [hasTexture, setHasTexture] = useState(false);
  const [activeWorkspace, setActiveWorkspace] = useState("data");
  const [target, setTarget] = useState("cranium");
  const [landmarks, setLandmarks] = useState({});
  const [aligning, setAligning] = useState(false);
  const [aligned, setAligned] = useState(false);
  const [alignStatus, setAlignStatus] = useState("");

  async function handleUploaded({ sessionId: newSessionId, meshLabel: newMeshLabel, selectionHasTexture: newSelectionHasTexture }) {
    setSessionId(newSessionId);
    setMeshLabel(newMeshLabel);
    setSelectionHasTexture(newSelectionHasTexture);
    setWireframe(false);
    setLandmarks({}); // a fresh mesh means the old picks' coordinates no longer mean anything
    setAligned(false);
    setAlignStatus("");
    const { hasTexture: loadedHasTexture } = await viewerRef.current.displayMesh(meshUrl(newSessionId), {
      selectionHasTexture: newSelectionHasTexture,
    });
    setHasTexture(loadedHasTexture);
    setTextureEnabled(loadedHasTexture);
  }

  function handlePick(point) {
    // computed from prev, not the closed-over landmarks state - two picks
    // arriving in the same React batch (e.g. rapid clicks) would otherwise
    // both see the same stale "next" name and the second would clobber the
    // first instead of filling the next slot.
    setLandmarks((prev) => {
      const name = nextUnpickedLandmark(prev);
      return name ? { ...prev, [name]: point } : prev;
    });
  }

  function handleDrag(name, point) {
    setLandmarks((prev) => ({ ...prev, [name]: point }));
  }

  // one path back to an interactive/pickable state - clears picks and any
  // registration result, redisplays the original mesh.
  async function handleReset() {
    setLandmarks({});
    setAligned(false);
    setAlignStatus("");
    await viewerRef.current.displayMesh(meshUrl(sessionId, "original"), { selectionHasTexture });
  }

  // the registration result IS what's on screen right now (no /clip step
  // yet to re-derive it fresh) - switching target while aligned would
  // otherwise leave a stale registered mesh showing for the old target, so
  // this reverts to original and clears aligned, but keeps the picks
  // (they're raw-mesh coordinates, independent of target) so re-aligning
  // is one click, not a re-pick.
  async function handleTargetChange(newTarget) {
    setTarget(newTarget);
    if (aligned) {
      setAligned(false);
      setAlignStatus("");
      await viewerRef.current.displayMesh(meshUrl(sessionId, "original"), { selectionHasTexture });
    }
  }

  async function handleAlign() {
    setAligning(true);
    setAlignStatus("Aligning...");
    try {
      await startAlign(sessionId, { target, landmarks: LANDMARK_NAMES.map((n) => landmarks[n]) });
      const result = await pollStatus(sessionId);
      if (result.status === "error") {
        setAlignStatus(`Error: ${result.error}`);
        return;
      }
      await viewerRef.current.displayMesh(meshUrl(sessionId, "registered"), { selectionHasTexture });
      setAligned(true);
      setAlignStatus("Aligned: ✓");
    } catch (err) {
      setAlignStatus(`Failed to start: ${err.message}`);
    } finally {
      setAligning(false);
    }
  }

  const onRegisterTab = activeWorkspace === "register";
  const pickingEnabled = onRegisterTab && !aligned;

  return (
    <Shell
      contextLabel={meshLabel}
      workspaces={WORKSPACES}
      activeWorkspace={activeWorkspace}
      onWorkspaceChange={setActiveWorkspace}
      inspectorTitle={onRegisterTab ? "Register" : "Data"}
      inspector={
        onRegisterTab ? (
          <RegisterPanel
            target={target}
            onTargetChange={handleTargetChange}
            landmarks={landmarks}
            aligned={aligned}
            aligning={aligning}
            alignStatus={alignStatus}
            onAlign={handleAlign}
            onReset={handleReset}
          />
        ) : (
          <>
            <UploadPanel onUploaded={handleUploaded} />
            {sessionId != null && (
              <MeshViewToggles
                wireframe={wireframe}
                onWireframeChange={setWireframe}
                textureEnabled={textureEnabled}
                onTextureChange={setTextureEnabled}
                textureDisabled={!hasTexture}
              />
            )}
          </>
        )
      }
      workspace={
        <>
          <Viewer
            ref={viewerRef}
            wireframe={wireframe}
            textureEnabled={textureEnabled}
            landmarks={landmarks}
            landmarkColors={LANDMARK_COLORS}
            onPick={pickingEnabled ? handlePick : undefined}
            onDrag={pickingEnabled ? handleDrag : undefined}
          />
          {sessionId == null && <p className="hint overlay">Upload a mesh to begin.</p>}
        </>
      }
    />
  );
}

export default App;
