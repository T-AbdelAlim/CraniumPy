import { useEffect, useRef, useState } from "react";
import Shell from "./components/shell/Shell.jsx";
import Viewer from "./components/Viewer.jsx";
import UploadPanel from "./workspaces/data/UploadPanel.jsx";
import MeshViewToggles from "./workspaces/data/MeshViewToggles.jsx";
import PreprocessingPanel from "./workspaces/preprocessing/PreprocessingPanel.jsx";
import AnalysisPanel from "./workspaces/analysis/AnalysisPanel.jsx";
import {
  meshUrl,
  startAlign,
  startClip,
  startRun,
  pollStatus,
  getRegisteredTransform,
  fetchShippedTemplates,
  templateMeshUrl,
  customTemplateMeshUrl,
  uploadCustomTemplate,
  nicpPreviewMeshUrl,
  saveMeshes,
  meshesBundleUrl,
  getResults,
  saveAnalysis,
  analysisBundleUrl,
} from "./api/sessions.js";
import { LANDMARK_NAMES, ALT_FRONTAL_NAME, LANDMARK_COLORS, nextUnpickedLandmark } from "./lib/landmarks.js";
import { heatmapMaxAbs } from "./three/measurementsLayer.js";
import { applyTransform, applyInverseTransform } from "./lib/transform.js";
import { defaultTemplateForTarget, templateChoiceStorageKey, customTemplatePathStorageKey } from "./lib/templates.js";
import { isDesktopApp, pickFileNative, pickFolderNative } from "./lib/desktop.js";

const WORKSPACES = [
  { id: "data", label: "Data" },
  { id: "preprocessing", label: "Preprocessing" },
  { id: "analysis", label: "Analysis" },
];

// cumulative % through run-pipeline's two chained jobs (/clip then /run),
// keyed by pipeline.py's own stage names - not measured, just ordered so
// the slow step (repair, pymeshfix) gets the most room on the bar. "repair"
// only actually shows up on the first press per session (cached after
// that) - on a cached press the bar just jumps straight from "register" to
// "clip", which is honest since that phase really was fast that time.
// "nicp" isn't in here - fitting a template is its own separate action
// (see handleFitTemplate) with its own numeric, stiffness-step-weighted
// progress bar, not squeezed into this coarse stage-weight guess.
const RUN_STAGE_PROGRESS = { register: 5, repair: 15, clip: 60, resample: 75, analyze: 92 };

const NICP_DEFAULTS = { alphaStart: 200, alphaEnd: 1, alphaSteps: 20, gamma: 1.0, distThreshold: 10.0, innerIters: 3 };

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
  const [useAltFrontal, setUseAltFrontal] = useState(false);
  const [landmarks, setLandmarks] = useState({}); // always raw-mesh coordinates

  // mirrors legacy's exact flag set (app.js:715-745) - see the plan for why
  // this isn't simplified down to a couple of booleans.
  const [alignSucceeded, setAlignSucceeded] = useState(false);
  const [landmarksChangedSinceAlign, setLandmarksChangedSinceAlign] = useState(true);
  const [adjustingInAlignedFrame, setAdjustingInAlignedFrame] = useState(false);
  const [registeredTransform, setRegisteredTransform] = useState(null);
  const [pipelineRan, setPipelineRan] = useState(false);
  const [aligning, setAligning] = useState(false);
  const [alignStatus, setAlignStatus] = useState("");

  const [comTranslation, setComTranslation] = useState(true);
  // "none" | "resample" - mutually exclusive ways to finalize the clipped
  // mesh before measuring. fitting a template (NICP) is a separate action
  // (see handleFitTemplate), not one of these - it needs a real, completed
  // run to fit onto (see resetPreprocessingState/pipelineRan gating below),
  // not something you'd pick before that run even happens.
  const [resampleMode, setResampleMode] = useState("none");
  const [vertexCount, setVertexCount] = useState(10000);
  const [nicpParams, setNicpParams] = useState(NICP_DEFAULTS);
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [runStarted, setRunStarted] = useState(false);
  const [runProgress, setRunProgress] = useState(0);
  const [runStatus, setRunStatus] = useState("");
  const [runError, setRunError] = useState(false);
  // "fit template" - a separate, explicit action against the already-
  // finished result mesh (see handleFitTemplate), with its own progress
  // bar driven by real stiffness-step counts instead of a guessed stage
  // weight, plus a live preview of the template converging (see
  // nicpPollingRef below).
  const [fittingTemplate, setFittingTemplate] = useState(false);
  const [nicpFitStarted, setNicpFitStarted] = useState(false);
  const [nicpProgress, setNicpProgress] = useState(0);
  const [nicpStatus, setNicpStatus] = useState("");
  const [nicpError, setNicpError] = useState(false);
  const nicpPollingRef = useRef(false);
  const [savingMeshes, setSavingMeshes] = useState(false);
  const [saveMeshesStatus, setSaveMeshesStatus] = useState("");
  // desktop-only override for where save/export writes - null means the
  // default (next to the original mesh file, session.source_dir on the
  // backend). shared between "save meshes" and "export analysis" since
  // it's one destination choice, not two.
  const [saveDestDir, setSaveDestDir] = useState(null);
  // bumped after every displayMesh() call so the template-overlay effect
  // (below) knows to re-show against whatever mesh is now on screen -
  // Viewer.displayMesh already drops any active overlay itself since the
  // mesh it was comparing against is about to be disposed.
  const [meshRevision, setMeshRevision] = useState(0);

  const [shippedTemplates, setShippedTemplates] = useState([]);
  const [showTemplateOverlay, setShowTemplateOverlay] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [customTemplatePath, setCustomTemplatePath] = useState(""); // desktop
  const [customTemplateBlobUrl, setCustomTemplateBlobUrl] = useState(""); // browser
  const [customTemplateName, setCustomTemplateName] = useState("");
  const [templateOffset, setTemplateOffset] = useState(null);
  const [templateStatus, setTemplateStatus] = useState("");

  const [analysisResults, setAnalysisResults] = useState(null);
  const [analysisStatus, setAnalysisStatus] = useState("");
  const [exportingAnalysis, setExportingAnalysis] = useState(false);
  const [exportAnalysisStatus, setExportAnalysisStatus] = useState("");

  async function handleUploaded({ sessionId: newSessionId, meshLabel: newMeshLabel, selectionHasTexture: newSelectionHasTexture }) {
    setSessionId(newSessionId);
    setMeshLabel(newMeshLabel);
    setSelectionHasTexture(newSelectionHasTexture);
    setWireframe(false);
    resetPreprocessingState();
    const { hasTexture: loadedHasTexture } = await viewerRef.current.displayMesh(meshUrl(newSessionId), {
      selectionHasTexture: newSelectionHasTexture,
    });
    setHasTexture(loadedHasTexture);
    setTextureEnabled(loadedHasTexture);
    setMeshRevision((n) => n + 1);
  }

  function resetPreprocessingState() {
    setLandmarks({});
    setAlignSucceeded(false);
    setAdjustingInAlignedFrame(false);
    setRegisteredTransform(null);
    setPipelineRan(false);
    setLandmarksChangedSinceAlign(true);
    setAlignStatus("");
    setRunningPipeline(false);
    setRunStarted(false);
    setRunProgress(0);
    setRunStatus("");
    setRunError(false);
    setShowTemplateOverlay(false);
    nicpPollingRef.current = false;
    setFittingTemplate(false);
    setNicpFitStarted(false);
    setNicpProgress(0);
    setNicpStatus("");
    setNicpError(false);
    setSavingMeshes(false);
    setSaveMeshesStatus("");
    setSaveDestDir(null);
    setAnalysisResults(null);
    setAnalysisStatus("");
    setExportingAnalysis(false);
    setExportAnalysisStatus("");
  }

  // desktop-only: opens the native folder dialog and remembers the choice
  // for both "save meshes" and "export analysis" - null (the default)
  // means "next to the original mesh file", handled entirely on the
  // backend (see api/schemas.py's SaveRequest.dest_dir).
  async function handleChooseSaveFolder() {
    const folder = await pickFolderNative((msg) => setSaveMeshesStatus(`Couldn't open the folder picker: ${msg}`));
    if (folder) setSaveDestDir(folder);
  }

  function handleUseDefaultSaveFolder() {
    setSaveDestDir(null);
  }

  // desktop: writes straight next to the source file (or saveDestDir, if
  // the user picked one via "change save folder..."); browser: downloads a
  // zip. tries the desktop path first and falls back on exactly a 400 (no
  // real source path for this session) - same pattern legacy's save-results
  // button used (frontend_legacy/app.js:1473-1497).
  async function handleSaveMeshes() {
    setSavingMeshes(true);
    if (isDesktopApp()) {
      setSaveMeshesStatus("Saving...");
      try {
        const { saved_to: savedTo } = await saveMeshes(sessionId, saveDestDir);
        setSaveMeshesStatus(`Saved to ${savedTo}`);
        setSavingMeshes(false);
        return;
      } catch (err) {
        if (err.status !== 400) {
          setSaveMeshesStatus(`Save failed: ${err.message}`);
          setSavingMeshes(false);
          return;
        }
      }
    }
    setSaveMeshesStatus("");
    setSavingMeshes(false);
    window.location.href = meshesBundleUrl(sessionId);
  }

  useEffect(() => {
    fetchShippedTemplates()
      .then(setShippedTemplates)
      .catch(() => {});
  }, []);

  // re-derives the default template choice whenever target changes,
  // preferring whatever was last picked for that target (remembered
  // per-target, same as legacy) - ported from
  // frontend_legacy/app.js's populateTemplateSelect. deliberately not
  // re-run on useAltFrontal/comTranslation alone (matches legacy, which
  // only re-populates on a target change) - toggling those updates what
  // the *next* target switch defaults to, not the current selection.
  //
  // gated on shippedTemplates actually being loaded: setting
  // selectedTemplate before the <select>'s real options exist briefly
  // renders a value with nothing to match it, and the browser's own
  // selection-repair for that mismatch can fire a spurious change event
  // once the options do arrive - which looks exactly like the user
  // picking "custom" and gets persisted to localStorage. waiting for the
  // list avoids ever rendering that mismatch in the first place.
  useEffect(() => {
    if (shippedTemplates.length === 0) return;
    const remembered = localStorage.getItem(templateChoiceStorageKey(target));
    setSelectedTemplate(remembered || defaultTemplateForTarget(target, useAltFrontal, comTranslation));
    setCustomTemplatePath(localStorage.getItem(customTemplatePathStorageKey(target)) || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, shippedTemplates]);

  function handleTemplateChange(name) {
    setSelectedTemplate(name);
    localStorage.setItem(templateChoiceStorageKey(target), name);
  }

  async function handleCustomTemplateBrowse() {
    const paths = await pickFileNative(false, (msg) => setTemplateStatus(`Couldn't open the file picker: ${msg}`));
    if (!paths || paths.length === 0) return;
    setCustomTemplatePath(paths[0]);
    localStorage.setItem(customTemplatePathStorageKey(target), paths[0]);
  }

  async function handleCustomTemplateFile(file) {
    if (!file) return;
    try {
      if (customTemplateBlobUrl) URL.revokeObjectURL(customTemplateBlobUrl);
      const blobUrl = await uploadCustomTemplate(file);
      setCustomTemplateBlobUrl(blobUrl);
      setCustomTemplateName(file.name);
    } catch (err) {
      setTemplateStatus(`Upload failed: ${err.message}`);
    }
  }

  // resolves the current template selection to a loadable GLB url - null
  // if "custom" is picked but nothing's actually there yet.
  function resolveTemplateUrl() {
    if (selectedTemplate !== "custom") return templateMeshUrl(selectedTemplate);
    return isDesktopApp() ? (customTemplatePath ? customTemplateMeshUrl(customTemplatePath) : null) : customTemplateBlobUrl || null;
  }

  // gated on pipelineRan, not just showTemplateOverlay - comparing against
  // an /align-only mesh (no repair/CoM-nudge/clip yet) is misleading, so
  // the comparison only ever runs against a completed "preprocess mesh"
  // result. PreprocessingPanel only renders the checkbox once pipelineRan
  // anyway, but this covers the case where pipelineRan flips back to false
  // (reset) while a comparison from a previous run was still showing.
  useEffect(() => {
    async function refresh() {
      if (!showTemplateOverlay || !pipelineRan) {
        viewerRef.current?.hideTemplateOverlay();
        setTemplateOffset(null);
        setTemplateStatus("");
        return;
      }
      const url = resolveTemplateUrl();
      if (!url) {
        setTemplateStatus("Pick a custom template file first.");
        setTemplateOffset(null);
        return;
      }
      const offset = await viewerRef.current.showTemplateOverlay(url);
      setTemplateOffset(offset);
      setTemplateStatus(offset ? "" : "Upload a mesh first.");
    }
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showTemplateOverlay, pipelineRan, selectedTemplate, customTemplatePath, customTemplateBlobUrl, meshRevision]);

  // the mesh currently on screen is the aligned one for as long as
  // alignSucceeded holds (reset is the only thing that reverts to the
  // original) - so any point raycast off it, whether from a fresh pick or
  // a drag, is in the aligned frame and needs converting back to raw for
  // storage. this is keyed on alignSucceeded rather than
  // adjustingInAlignedFrame (which is a marker-visibility toggle, not a
  // frame indicator) - the bug this fixes: picking a new landmark (e.g.
  // the secondary frontal one, added after an initial align) always used
  // to store the raw click point untransformed, silently corrupting it.
  function handlePick(point) {
    const raw = alignSucceeded ? applyInverseTransform(point, registeredTransform) : point;
    setLandmarks((prev) => {
      const name = nextUnpickedLandmark(prev, useAltFrontal);
      return name ? { ...prev, [name]: raw } : prev;
    });
    setLandmarksChangedSinceAlign(true);
  }

  function handleDrag(name, point) {
    const raw = alignSucceeded ? applyInverseTransform(point, registeredTransform) : point;
    setLandmarks((prev) => ({ ...prev, [name]: raw }));
    setLandmarksChangedSinceAlign(true);
  }

  function handleTargetChange(newTarget) {
    setTarget(newTarget);
    if (newTarget !== "cranium" && useAltFrontal) {
      setUseAltFrontal(false);
      setLandmarks((prev) => {
        const { [ALT_FRONTAL_NAME]: _drop, ...rest } = prev;
        return rest;
      });
    }
  }

  function handleUseAltFrontalChange(enabled) {
    setUseAltFrontal(enabled);
    if (!enabled && ALT_FRONTAL_NAME in landmarks) {
      setLandmarks((prev) => {
        const { [ALT_FRONTAL_NAME]: _drop, ...rest } = prev;
        return rest;
      });
      // dropping an already-picked point that fed the current alignment
      // means what's on screen no longer matches the active landmark set.
      setLandmarksChangedSinceAlign(true);
    }
  }

  async function handleAdjustPicks() {
    if (!alignSucceeded) return;
    setAdjustingInAlignedFrame(true);
    setLandmarksChangedSinceAlign(true);
  }

  async function handleReset() {
    resetPreprocessingState();
    await viewerRef.current.displayMesh(meshUrl(sessionId, "original"), { selectionHasTexture });
    setMeshRevision((n) => n + 1);
  }

  async function handleAlign() {
    setAligning(true);
    setAlignStatus("Starting...");
    try {
      await startAlign(sessionId, {
        target,
        landmarks: LANDMARK_NAMES.map((n) => landmarks[n]),
        altFrontalLandmark: useAltFrontal ? landmarks[ALT_FRONTAL_NAME] : undefined,
      });
      const result = await pollStatus(sessionId, (stage, detail) => {
        if (stage === "error") setAlignStatus(`Error: ${detail}`);
        else if (stage !== "done") setAlignStatus(`${stage}${detail ? " - " + detail : ""}...`);
      });
      if (result.status === "done") {
        await viewerRef.current.displayMesh(meshUrl(sessionId, "registered"), { selectionHasTexture });
        setMeshRevision((n) => n + 1);
        const transform = await getRegisteredTransform(sessionId);
        setRegisteredTransform(transform);
        setAlignSucceeded(true);
        setAdjustingInAlignedFrame(false);
        setLandmarksChangedSinceAlign(false);
        setAlignStatus("Rigid alignment: ✓");
      }
    } catch (err) {
      setAlignStatus(`Failed to start: ${err.message}`);
    } finally {
      setAligning(false);
    }
  }

  // resolves the current template selection into what /run's NicpConfig
  // needs - null if "custom" is picked in browser mode (no persisted
  // server-side mesh to point a backend job at - the browser-uploaded blob
  // only ever lived in this tab, see uploadCustomTemplate). returns
  // undefined (not null) in that unsupported-combo case so the caller can
  // tell "no template pickable at all yet" apart from "a real config".
  function resolveNicpRequestConfig() {
    if (selectedTemplate !== "custom") return { template: selectedTemplate, ...nicpParams };
    if (isDesktopApp() && customTemplatePath) return { customTemplatePath, ...nicpParams };
    return undefined;
  }

  async function handleRunPipeline() {
    setRunningPipeline(true);
    setRunStarted(true);
    setRunError(false);
    setRunProgress(0);
    setRunStatus("");

    let lastPercent = 0;
    function onStage(stage, detail) {
      if (stage === "error") {
        setRunError(true);
        setRunStatus(`error: ${detail}`);
      } else if (stage !== "done") {
        // stages aren't strictly ordered - register_and_clip_cranial
        // re-registers the now-repaired mesh right after repair finishes,
        // so "register" legitimately reports a second time, after
        // "repair", on a fresh (uncached) repair. clamping to never go
        // below lastPercent keeps the bar moving forward regardless.
        const percent = Math.max(RUN_STAGE_PROGRESS[stage] ?? lastPercent, lastPercent);
        lastPercent = percent;
        setRunProgress(percent);
        setRunStatus(detail ? `${stage} - ${detail}` : stage);
      }
    }

    try {
      await startClip(sessionId, {
        target,
        landmarks: LANDMARK_NAMES.map((n) => landmarks[n]),
        altFrontalLandmark: useAltFrontal ? landmarks[ALT_FRONTAL_NAME] : undefined,
        comTranslation,
      });
      const clipResult = await pollStatus(sessionId, onStage);
      if (clipResult.status !== "done") return;

      await startRun(sessionId, { nVertices: resampleMode === "resample" ? vertexCount : null });
      const runResult = await pollStatus(sessionId, onStage);
      if (runResult.status === "done") {
        setPipelineRan(true);
        // default to showing the template comparison once there's a real,
        // fully-preprocessed mesh to compare against - the user has to
        // opt back out, not in, every time.
        setShowTemplateOverlay(true);
        await viewerRef.current.displayMesh(meshUrl(sessionId, "result"), { selectionHasTexture });
        setMeshRevision((n) => n + 1);
        setRunProgress(100);
        setRunStatus("Run complete: ✓");
      }
    } catch (err) {
      setRunError(true);
      setRunStatus(`failed to start: ${err.message}`);
    } finally {
      setRunningPipeline(false);
    }
  }

  // fits the selected template onto the already-completed result mesh -
  // re-invokes /run (no /clip - re-targets the same already-clipped mesh,
  // same "tweak and re-run without redoing clip" pattern handleRunPipeline
  // itself relies on), only reachable once pipelineRan. runs its own
  // progress bar off the real (current, total) stiffness-step counts
  // instead of a guessed stage weight, and polls the live preview endpoint
  // in parallel so the template visibly deforms onto the mesh as it fits.
  // deliberately never touches result_mesh/craniometrics on the backend
  // (see /run's handler) - it only produces the extra saved artifact
  // (session.nicp_result_mesh), so there's nothing to reload into the
  // viewer once it's done; hideNicpPreview alone already puts the viewer
  // back to showing the patient's own mesh, undecorated.
  async function handleFitTemplate() {
    const nicpConfig = resolveNicpRequestConfig();
    if (nicpConfig === undefined) {
      setNicpError(true);
      setNicpStatus("pick a custom template file first (or use a shipped one)");
      return;
    }

    setFittingTemplate(true);
    setNicpFitStarted(true);
    setNicpError(false);
    setNicpProgress(0);
    setNicpStatus("");

    nicpPollingRef.current = true;
    (async () => {
      while (nicpPollingRef.current) {
        try {
          await viewerRef.current.updateNicpPreview(`${nicpPreviewMeshUrl(sessionId)}?t=${Date.now()}`);
        } catch {
          // no preview yet (fit hasn't finished its first stiffness step)
          // or a transient load error - either way, just try again next
          // tick rather than surfacing it as a real failure.
        }
        await new Promise((resolve) => setTimeout(resolve, 800));
      }
    })();

    let lastPercent = 0;
    function onStage(stage, detail, progress) {
      if (stage === "error") {
        setNicpError(true);
        setNicpStatus(`error: ${detail}`);
        return;
      }
      if (stage === "done") return;
      let percent = lastPercent;
      if (stage === "nicp" && progress?.total) {
        percent = Math.round((progress.current / progress.total) * 100);
      }
      percent = Math.max(percent, lastPercent);
      lastPercent = percent;
      setNicpProgress(percent);
      setNicpStatus(
        stage === "nicp" && progress?.total
          ? `fitting template - stiffness step ${progress.current}/${progress.total}`
          : detail
            ? `${stage} - ${detail}`
            : stage,
      );
    }

    try {
      await startRun(sessionId, { nVertices: null, nicp: nicpConfig });
      const result = await pollStatus(sessionId, onStage);
      if (result.status === "done") {
        setNicpProgress(100);
        setNicpStatus("Fit complete: ✓");
      }
    } catch (err) {
      setNicpError(true);
      setNicpStatus(`failed to start: ${err.message}`);
    } finally {
      nicpPollingRef.current = false;
      // the only place the fit's visualization (red wireframe+nodes
      // template, dimmed patient mesh) ever gets torn down, success or
      // failure alike - puts the viewer back to showing the patient's own
      // mesh normally.
      viewerRef.current?.hideNicpPreview();
      setFittingTemplate(false);
      // if "compare to template" was checked, its mesh just got repurposed
      // as the deforming preview (see Viewer.jsx's updateNicpPreview) and
      // needs to be redrawn as a normal static comparison again - the
      // effect above already does that, it just needs a nudge to re-run.
      setMeshRevision((n) => n + 1);
    }
  }

  // fetches craniometrics/asymmetry once a completed run exists and the
  // Analysis tab is actually open, and drives the matching live viewer
  // overlay (HC-line/BPD/OFD for cranial, heatmap for facial) - re-fetches
  // on meshRevision too, so re-running the pipeline (target switch, a
  // fresh NICP fit) with the tab already open picks up the new numbers
  // instead of showing stale ones.
  useEffect(() => {
    const onAnalysisTab = activeWorkspace === "analysis";
    if (!onAnalysisTab || !pipelineRan || !sessionId) {
      viewerRef.current?.hideMeasurementsOverlay();
      viewerRef.current?.hideHeatmap();
      return;
    }
    let cancelled = false;
    (async () => {
      setAnalysisStatus("Loading...");
      try {
        const results = await getResults(sessionId);
        if (cancelled) return;
        setAnalysisResults(results);
        setAnalysisStatus("");
        if (results.craniometrics) {
          viewerRef.current?.showMeasurementsOverlay({
            hcPolygon: results.craniometrics.hc_slice_polygon,
            frontOpt: results.craniometrics.front_opt,
            occOpt: results.craniometrics.occ_opt,
            lhOpt: results.craniometrics.lh_opt,
            rhOpt: results.craniometrics.rh_opt,
          });
        }
        if (results.asymmetry) {
          viewerRef.current?.showHeatmap(results.asymmetry.heatmap);
        }
      } catch (err) {
        if (!cancelled) setAnalysisStatus(`Failed to load results: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace, pipelineRan, sessionId, meshRevision]);

  // same desktop-first-then-bundle-download fallback as handleSaveMeshes.
  async function handleExportAnalysis() {
    setExportingAnalysis(true);
    if (isDesktopApp()) {
      setExportAnalysisStatus("Exporting...");
      try {
        const { saved_to: savedTo } = await saveAnalysis(sessionId, saveDestDir);
        setExportAnalysisStatus(`Saved to ${savedTo}`);
        setExportingAnalysis(false);
        return;
      } catch (err) {
        if (err.status !== 400) {
          setExportAnalysisStatus(`Export failed: ${err.message}`);
          setExportingAnalysis(false);
          return;
        }
      }
    }
    setExportAnalysisStatus("");
    setExportingAnalysis(false);
    window.location.href = analysisBundleUrl(sessionId);
  }

  // what the viewer actually shows: raw picks on the raw mesh before
  // alignment, the same picks re-projected into the aligned frame while
  // either "adjust picks" is active or the secondary-frontal checkbox gets
  // ticked post-align (so there's something to click against for the extra
  // point), or nothing once aligned and neither applies - this alone gives
  // "remove landmarks after registration, only show them when adjust (or
  // the alt-frontal pick) is toggled" with no separate hide/show
  // bookkeeping. locked to hidden again once the pipeline has run - landmark
  // *positions* are locked in at that point (align/adjust picks stay
  // disabled); only target/resample tuning can still trigger a re-run.
  const showAlignedLandmarks = alignSucceeded && !pipelineRan && (adjustingInAlignedFrame || useAltFrontal);
  const displayLandmarks = !alignSucceeded
    ? landmarks
    : showAlignedLandmarks
      ? Object.fromEntries(Object.entries(landmarks).map(([n, p]) => [n, applyTransform(p, registeredTransform)]))
      : {};

  const onPreprocessingTab = activeWorkspace === "preprocessing";
  const onAnalysisTab = activeWorkspace === "analysis";
  const inspectorTitle = onPreprocessingTab ? "Preprocessing" : onAnalysisTab ? "Analysis" : "Data";

  return (
    <Shell
      contextLabel={meshLabel}
      workspaces={WORKSPACES}
      activeWorkspace={activeWorkspace}
      onWorkspaceChange={setActiveWorkspace}
      inspectorTitle={inspectorTitle}
      inspector={
        onPreprocessingTab ? (
          <PreprocessingPanel
            target={target}
            onTargetChange={handleTargetChange}
            useAltFrontal={useAltFrontal}
            onUseAltFrontalChange={handleUseAltFrontalChange}
            landmarks={landmarks}
            alignSucceeded={alignSucceeded}
            landmarksChangedSinceAlign={landmarksChangedSinceAlign}
            aligning={aligning}
            pipelineRan={pipelineRan}
            alignStatus={alignStatus}
            onAlign={handleAlign}
            onAdjustPicks={handleAdjustPicks}
            onReset={handleReset}
            comTranslation={comTranslation}
            onComTranslationChange={setComTranslation}
            resampleMode={resampleMode}
            onResampleModeChange={setResampleMode}
            vertexCount={vertexCount}
            onVertexCountChange={setVertexCount}
            nicpParams={nicpParams}
            onNicpParamsChange={setNicpParams}
            onRunPipeline={handleRunPipeline}
            runningPipeline={runningPipeline}
            runStarted={runStarted}
            runProgress={runProgress}
            runStatus={runStatus}
            runError={runError}
            shippedTemplates={shippedTemplates}
            showTemplateOverlay={showTemplateOverlay}
            onShowTemplateOverlayChange={setShowTemplateOverlay}
            selectedTemplate={selectedTemplate}
            onTemplateChange={handleTemplateChange}
            isDesktop={isDesktopApp()}
            customTemplatePath={customTemplatePath}
            customTemplateName={customTemplateName}
            onCustomTemplateBrowse={handleCustomTemplateBrowse}
            onCustomTemplateFile={handleCustomTemplateFile}
            templateOffset={templateOffset}
            templateStatus={templateStatus}
            onFitTemplate={handleFitTemplate}
            fittingTemplate={fittingTemplate}
            nicpFitStarted={nicpFitStarted}
            nicpProgress={nicpProgress}
            nicpStatus={nicpStatus}
            nicpError={nicpError}
            onSaveMeshes={handleSaveMeshes}
            savingMeshes={savingMeshes}
            saveMeshesStatus={saveMeshesStatus}
            saveDestDir={saveDestDir}
            onChooseSaveFolder={handleChooseSaveFolder}
            onUseDefaultSaveFolder={handleUseDefaultSaveFolder}
          />
        ) : onAnalysisTab ? (
          <AnalysisPanel
            pipelineRan={pipelineRan}
            analysisResults={analysisResults}
            analysisStatus={analysisStatus}
            onExportAnalysis={handleExportAnalysis}
            exportingAnalysis={exportingAnalysis}
            exportAnalysisStatus={exportAnalysisStatus}
            isDesktop={isDesktopApp()}
            saveDestDir={saveDestDir}
            onChooseSaveFolder={handleChooseSaveFolder}
            onUseDefaultSaveFolder={handleUseDefaultSaveFolder}
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
            landmarks={displayLandmarks}
            landmarkColors={LANDMARK_COLORS}
            onPick={onPreprocessingTab ? handlePick : undefined}
            onDrag={onPreprocessingTab ? handleDrag : undefined}
          />
          {sessionId == null && <p className="hint overlay">Upload a mesh to begin.</p>}
          {onAnalysisTab && analysisResults?.asymmetry && (
            <div className="heatmap-scalar-bar">
              <span>+{heatmapMaxAbs(analysisResults.asymmetry.heatmap).toFixed(1)} mm</span>
              <div className="scalar-bar-gradient" />
              <span>-{heatmapMaxAbs(analysisResults.asymmetry.heatmap).toFixed(1)} mm</span>
            </div>
          )}
          {fittingTemplate && (
            <div className="viewer-legend">
              <div className="viewer-legend-row">
                <span className="viewer-legend-swatch" style={{ background: "#d1453d" }} />
                deforming template
              </div>
              <div className="viewer-legend-row">
                <span className="viewer-legend-swatch" style={{ background: "#e8d9c0" }} />
                target mesh (patient)
              </div>
            </div>
          )}
          {/* the static "compare to template" overlay - only when a fit
              isn't also using the same mesh for its own legend above (see
              Viewer.jsx's updateNicpPreview, which repurposes this exact
              object during a fit). templateOffset is only non-null once
              the overlay actually rendered against a real mesh. */}
          {!fittingTemplate && onPreprocessingTab && showTemplateOverlay && templateOffset && (
            <div className="viewer-legend">
              <div className="viewer-legend-row">
                <span className="viewer-legend-swatch" style={{ background: "#60a5fa" }} />
                template
              </div>
              <div className="viewer-legend-row">
                <span className="viewer-legend-swatch" style={{ background: "#e8d9c0" }} />
                patient mesh
              </div>
            </div>
          )}
        </>
      }
    />
  );
}

export default App;
