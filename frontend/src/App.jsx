import { useEffect, useRef, useState } from "react";
import Shell from "./components/shell/Shell.jsx";
import Viewer from "./components/Viewer.jsx";
import UploadPanel from "./workspaces/data/UploadPanel.jsx";
import MeshViewToggles from "./workspaces/data/MeshViewToggles.jsx";
import PreprocessingPanel from "./workspaces/preprocessing/PreprocessingPanel.jsx";
import AnalysisPanel from "./workspaces/analysis/AnalysisPanel.jsx";
import PatientMetadataForm from "./components/PatientMetadataForm.jsx";
import CohortWorkspace from "./workspaces/cohort/CohortWorkspace.jsx";
import LongitudinalWorkspace from "./workspaces/longitudinal/LongitudinalWorkspace.jsx";
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
  uploadSession,
  openFromPaths,
  nicpPreviewMeshUrl,
  nicpResultMeshUrl,
  saveMeshes,
  meshesBundleUrl,
  getResults,
  saveAnalysis,
  analysisBundleUrl,
  switchTarget,
} from "./api/sessions.js";
import { LANDMARK_NAMES, ALT_FRONTAL_NAME, LANDMARK_COLORS, nextUnpickedLandmark } from "./lib/landmarks.js";
import { heatmapMaxAbs } from "./three/measurementsLayer.js";
import { applyTransform, applyInverseTransform } from "./lib/transform.js";
import { defaultTemplateForTarget, templateChoiceStorageKey, customTemplatePathStorageKey } from "./lib/templates.js";
import { isDesktopApp, pickFileNative, pickFolderNative, pickExcelFileNative, waitForNativeDropPaths, openFolderNative } from "./lib/desktop.js";
import { hasMeshFile, hasTextureFile, primaryMeshFile } from "./lib/meshFiles.js";

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

// backend stage identifiers aren't always meant to be read literally -
// "starting" in particular is just the one-tick placeholder
// SessionStore.run_job (api/sessions.py) sets before a job's real first
// stage report ever arrives, so shown as-is it's just the bare word
// "starting" sitting under a 0% bar with no detail attached. every status
// line driven by a poll loop's (stage, detail) callback should read
// through this instead of interpolating stage/detail directly.
function describeStage(stage, detail) {
  if (stage === "starting") return "Preparing...";
  return detail ? `${stage} - ${detail}` : stage;
}

// just the filename off a full path, Windows (backslash) or POSIX (forward
// slash) - cohortPath comes from a native file dialog, so it's always a
// real OS path, never a URL.
function baseName(path) {
  return path.split(/[\\/]/).pop();
}

// see displayedMeshKeyRef. target has to be part of this key, not just
// descriptor - /mesh/{stage} (meshUrl below) doesn't take target in the
// URL at all, it serves whatever the session's own active_target
// currently is (see api/sessions.py's Session.switch_active_target) - so
// the exact same descriptor ("result", "registered", ...) refers to a
// completely different mesh once the active target changes. leaving
// target out of this key was the bug behind "switch to cranium, run it,
// switch back to face and the mesh doesn't change" - both targets' own
// "result" stage collided on the same key, so the cache check wrongly
// concluded nothing needed reloading, leaving cranium's mesh on screen
// under face's own overlays/landmarks/template comparison.
function meshDisplayKey(sid, target, descriptor) {
  return `${sid}:${target}:${descriptor}`;
}

const NICP_DEFAULTS = { alphaStart: 200, alphaEnd: 1, alphaSteps: 20, gamma: 1.0, distThreshold: 10.0, innerIters: 3 };

// the fields that genuinely differ per IMAGE rather than per patient - reset
// to blank on a fresh upload even in "same patient, new image" mode (see
// handleUploaded/PatientMetadataForm's freeze toggle), where every other
// field carries over unchanged instead of being retyped. file_name/file_path
// aren't in this list - they're never frozen at all, always overwritten from
// whatever was just uploaded (see handleUploaded) - that's also what keeps a
// same-patient follow-up's cohort row from colliding with the first visit's:
// api/results_bundle.py's _row_key upserts on file_path/file_name, so two
// genuinely different files always land as two separate rows.
const PER_IMAGE_METADATA_FIELDS = ["date_imaging", "age_imaging", "image_timing", "surgical_status", "free_variable"];

// every patient/visit field, blank - file_name/file_path get filled in
// separately on upload (see handleUploaded), the rest are the user's to
// type. matches api/schemas.py's PatientMetadata field set.
const BLANK_PATIENT_METADATA = {
  file_name: "",
  file_path: "",
  patient_id: "",
  date_of_birth: "",
  diagnosis: "",
  sex: "",
  date_imaging: "",
  age_imaging: "",
  image_timing: "",
  surgical_status: "",
  treatment: "",
  date_of_intervention: "",
  age_intervention_months: "",
  free_variable: "",
};

function App() {
  const viewerRef = useRef(null);
  // "{sessionId}:{descriptor}" for whatever's currently loaded in the
  // viewer (descriptor is a /mesh/{stage} stage name, or "nicp-result") -
  // updated by every displayMesh call via markMeshDisplayed below.
  // handleTargetChange checks this before reloading anything: switching
  // between two targets that are BOTH still in their blank "never run"
  // state needs the original mesh on screen either way, so without this
  // check it would re-fetch/re-parse/re-frame the exact same GLB on every
  // toggle even though nothing visible actually changes.
  const displayedMeshKeyRef = useRef(null);
  const [sessionId, setSessionId] = useState(null);
  const [meshLabel, setMeshLabel] = useState("");
  // feedback for the viewer's own drag-and-drop drop zone (see
  // handleFilesDropped/Viewer.jsx's onFilesDropped) - separate from
  // UploadPanel's own local status text, since the drop target is the
  // viewer canvas, not the sidebar UploadPanel renders in. cleared on every
  // fresh upload (handleUploaded), regardless of which path produced it, so
  // a stale drop message can't linger over a mesh loaded by browsing instead.
  const [dropStatus, setDropStatus] = useState("");
  const [selectionHasTexture, setSelectionHasTexture] = useState(false);
  const [wireframe, setWireframe] = useState(false);
  const [textureEnabled, setTextureEnabled] = useState(false);
  const [hasTexture, setHasTexture] = useState(false);
  const [activeWorkspace, setActiveWorkspace] = useState("data");
  // "patients" (everything else in this file) | "cohort" (batch/cohort
  // analysis across already-exported patients - see
  // workspaces/cohort/CohortWorkspace.jsx) | "longitudinal" (side-by-side
  // comparison of two or more already-registered images of the same
  // patient, or against a reference - see
  // workspaces/longitudinal/LongitudinalWorkspace.jsx). a full remount on
  // switch, not a dual-mounted-hidden Viewer - see CohortWorkspace's own
  // module comment for why that tradeoff is fine for v1: the backend
  // session is untouched either way, only in-progress frontend
  // landmark/align state resets.
  const [appMode, setAppMode] = useState("patients");

  const [target, setTarget] = useState("cranium");
  const [useAltFrontal, setUseAltFrontal] = useState(false);
  const [landmarks, setLandmarks] = useState({}); // always raw-mesh coordinates
  // one captureTargetSnapshot() object per target that's been switched away
  // from this session (see below), reapplied by handleTargetChange when
  // switching back - so returning to a target already processed shows
  // exactly the scene left behind (mesh stage, template compare, analysis
  // results, all of it) instead of re-running align/clip/run against it.
  // mirrors the backend's own per-target snapshot (see api/sessions.py's
  // Session.switch_active_target) - the two are always written/read
  // together, in handleTargetChange, so they can't drift apart. reset on a
  // fresh upload/full reset, alongside everything else in
  // resetPreprocessingState.
  const [targetSnapshots, setTargetSnapshots] = useState({});

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
  // the REAL folder the last "save meshes"/"export analysis" actually
  // wrote to (the backend's own "saved_to", not saveDestDir - see
  // SaveFolderControl.jsx's own comment on why those two can differ) -
  // each has its own, since the two actions can land in different folders
  // (different settings -> different result folder name, see the
  // README's own "Saving your results" section). null until a desktop
  // save actually succeeds; "go to save folder" stays disabled until then.
  const [lastSavedMeshesFolder, setLastSavedMeshesFolder] = useState(null);
  const [lastSavedAnalysisFolder, setLastSavedAnalysisFolder] = useState(null);
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
  // "asymmetry" | "metopic" - only meaningful when a facial result carries
  // both (see craniumpy_core.metopic's module docstring) - AnalysisPanel's
  // mode toggle sets this, and it's what picks which live viewer overlay
  // shows (see the results-fetch effect below).
  const [analysisViewMode, setAnalysisViewMode] = useState("metopic");
  // mesh opacity while an Analysis overlay (HC-line, heatmap, or metopic
  // contour) is showing - never touches the overlay's own lines/markers,
  // just the underlying mesh surface (see Viewer.jsx's setMeshOpacity).
  // same slider for cranial and facial. 0.35 default keeps the overlay
  // readable without hiding the mesh surface entirely - see Viewer.jsx's
  // ANALYSIS_DEFAULT_MESH_OPACITY, which this mirrors.
  const [analysisMeshOpacity, setAnalysisMeshOpacity] = useState(0.35);
  // whether the NICP-fitted mesh (rather than the patient's own plain
  // result mesh) is what the viewer should be showing - a real user
  // choice (PreprocessingPanel's "continue with NICP mesh" checkbox, see
  // handleUseNicpMeshChange), not just a transient flag: it starts true
  // the moment a fit succeeds (see handleFitTemplate) but then persists
  // across workspace switches until the user says otherwise, the same way
  // every other per-target preprocessing choice does (see
  // captureTargetSnapshot/applyTargetSnapshot). craniometrics/frontal-
  // bossing/metopic overlays are all plain 3D points/lines, independent of
  // the mesh's own vertex layout, so they read correctly on either mesh -
  // but the asymmetry heatmap is a literal per-VERTEX-INDEX color array
  // computed against result_mesh's own vertices (see
  // craniumpy_core.asymmetry), so the Analysis-tab overlay effect below
  // always shows result_mesh specifically while asymmetry's heatmap is the
  // active view, regardless of this - there's no valid way to show a
  // result_mesh-indexed heatmap on the NICP mesh's own, entirely different
  // vertex set.
  const [showingNicpResult, setShowingNicpResult] = useState(false);
  // whether a NICP fit has actually SUCCEEDED for the current session+
  // target - separate from showingNicpResult (which the user can toggle
  // freely once this is true) so unchecking "continue with NICP mesh"
  // doesn't also hide the checkbox itself. reset alongside showingNicpResult
  // everywhere that resets it; never touched by the checkbox.
  const [nicpResultReady, setNicpResultReady] = useState(false);
  const [exportingAnalysis, setExportingAnalysis] = useState(false);
  const [exportAnalysisStatus, setExportAnalysisStatus] = useState("");
  // separate from exportAnalysisStatus above so the two lines can't get
  // concatenated/overwrite each other - only set on a successful desktop
  // save that actually targeted a cohort file (cohortMode !== "none"), see
  // handleExportAnalysis. cleared alongside it everywhere else.
  const [exportCohortStatus, setExportCohortStatus] = useState("");
  // "export analysis" checkboxes (AnalysisPanel, above the export button) -
  // a standing preference like saveDestDir/cohortMode below, not
  // per-target/per-run state, so it deliberately isn't reset by
  // resetPreprocessingState or the target-switch snapshot machinery.
  const [exportMeasurements, setExportMeasurements] = useState(true);
  const [exportAsymmetry, setExportAsymmetry] = useState(true);
  const [exportMeshes, setExportMeshes] = useState(true);

  // patient/visit metadata form (sidebar) - see PatientMetadataForm.jsx and
  // api/schemas.py's PatientMetadata. cohortMode/cohortPath deliberately
  // DON'T reset on a fresh upload (see handleUploaded) - unlike the 6
  // per-patient fields, "which cohort file am I building" is a
  // batch-level choice that should survive across a whole session of
  // uploading one patient after another, not just one.
  const [patientMetadata, setPatientMetadata] = useState(BLANK_PATIENT_METADATA);
  const [cohortMode, setCohortMode] = useState("none"); // "none" | "create" | "append"
  const [cohortPath, setCohortPath] = useState(null);
  // "same patient, new image" - see PatientMetadataForm's freeze toggle.
  // when on, a fresh upload keeps every field except file_name/file_path
  // (always overwritten - see PER_IMAGE_METADATA_FIELDS' own comment) and
  // PER_IMAGE_METADATA_FIELDS (reset blank, since those genuinely need new
  // input for a new image). stays on across uploads until the user turns
  // it off - processing a third, fourth, ... image of the same patient in
  // a row shouldn't need re-toggling each time.
  const [samePatientMode, setSamePatientMode] = useState(false);

  async function handleUploaded({
    sessionId: newSessionId,
    meshLabel: newMeshLabel,
    filePath: newFilePath,
    selectionHasTexture: newSelectionHasTexture,
  }) {
    setSessionId(newSessionId);
    setMeshLabel(newMeshLabel);
    setSelectionHasTexture(newSelectionHasTexture);
    setWireframe(false);
    setDropStatus("");
    resetPreprocessingState();
    if (samePatientMode) {
      // everything except file_name/file_path carries over unchanged, then
      // the per-image fields reset blank for fresh input - see
      // PER_IMAGE_METADATA_FIELDS.
      setPatientMetadata((prev) => {
        const next = { ...prev, file_name: newMeshLabel || "", file_path: newFilePath || "" };
        for (const field of PER_IMAGE_METADATA_FIELDS) next[field] = "";
        return next;
      });
    } else {
      // a fresh mesh means a new patient - carrying over the previous
      // patient's sex/treatment/etc by accident is worse than having to
      // retype, so every field resets, not just the identity ones.
      setPatientMetadata({ ...BLANK_PATIENT_METADATA, file_name: newMeshLabel || "", file_path: newFilePath || "" });
    }
    const { hasTexture: loadedHasTexture } = await viewerRef.current.displayMesh(meshUrl(newSessionId), {
      selectionHasTexture: newSelectionHasTexture,
    });
    displayedMeshKeyRef.current = meshDisplayKey(newSessionId, target, "original");
    setHasTexture(loadedHasTexture);
    setTextureEnabled(loadedHasTexture);
    setMeshRevision((n) => n + 1);
  }

  // dropped onto the viewer canvas (see Viewer.jsx's onFilesDropped) - an
  // alternative to UploadPanel's "choose file(s)..." browse button, only
  // wired up while the Data tab is active (see the Viewer prop below).
  // plain browser drag-and-drop never exposes a real filesystem path (same
  // limitation UploadPanel's own <input type=file> branch has) - in the
  // desktop app, waitForNativeDropPaths races pywebview's own native drop
  // resolution (see desktop/app.py's _register_native_drop) against a
  // short timeout, and if every dropped file resolved to a real path, this
  // opens straight from those paths instead - the exact same
  // openFromPaths flow "choose file(s)..." itself uses, so a dropped mesh
  // gets file_path pre-filled and can save straight back next to its
  // source, same as a browsed one. falls back to the plain browser-bytes
  // upload (no real path) whenever that didn't happen - the web app
  // always, or the rare case a path didn't resolve in time.
  async function handleFilesDropped(files) {
    const names = files.map((f) => f.name);
    if (!hasMeshFile(names)) {
      setDropStatus("No .ply/.obj/.stl found in the files you dropped");
      return;
    }
    setDropStatus("Uploading...");
    try {
      const nativePaths = await waitForNativeDropPaths();
      const resolvedPaths = nativePaths && names.every((n) => nativePaths[n]) ? names.map((n) => nativePaths[n]) : null;

      const { sessionId: newSessionId } = resolvedPaths ? await openFromPaths(resolvedPaths) : await uploadSession(files);
      const primaryName = primaryMeshFile(names);
      const filePath = resolvedPaths && primaryName ? resolvedPaths[names.indexOf(primaryName)] : "";

      // no success message - handleUploaded already clears dropStatus
      // (see its own setDropStatus("") near the top) as part of loading
      // the mesh, so the viewer just shows the loaded mesh, not text
      // sitting in the middle of it. (browsing still shows its own
      // vertex/face count, in UploadPanel's own sidebar status line - that
      // one isn't overlaid on the 3D view, so it stays.)
      await handleUploaded({
        sessionId: newSessionId,
        meshLabel: primaryName ?? "",
        filePath,
        selectionHasTexture: hasTextureFile(names),
      });
    } catch (err) {
      setDropStatus(`Upload failed: ${err.message}`);
    }
  }

  function handlePatientMetadataFieldChange(field, value) {
    setPatientMetadata((prev) => ({ ...prev, [field]: value }));
  }

  // "none" clears the cohort target immediately. "create"/"append" open the
  // matching native dialog (Save vs Open - see desktop/app.py's
  // pick_excel_file) and only commit to the new mode once a real path comes
  // back, so a cancelled dialog leaves the previous choice in place instead
  // of silently switching to a mode with no path behind it.
  async function handleCohortModeChange(mode) {
    if (mode === "none") {
      setCohortMode("none");
      setCohortPath(null);
      return;
    }
    const path = await pickExcelFileNative(mode === "create", (msg) =>
      setExportAnalysisStatus(`Couldn't open the file picker: ${msg}`)
    );
    if (path) {
      setCohortMode(mode);
      setCohortPath(path);
    }
  }

  function resetPreprocessingState() {
    setLandmarks({});
    setTargetSnapshots({});
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
    setShowingNicpResult(false);
    setNicpResultReady(false);
    setSavingMeshes(false);
    setSaveMeshesStatus("");
    setSaveDestDir(null);
    setLastSavedMeshesFolder(null);
    setLastSavedAnalysisFolder(null);
    setAnalysisResults(null);
    setAnalysisStatus("");
    setExportingAnalysis(false);
    setExportAnalysisStatus("");
    setExportCohortStatus("");
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

  // "go to save folder" (SaveFolderControl.jsx) - folder is whichever of
  // lastSavedMeshesFolder/lastSavedAnalysisFolder the caller's own control
  // is showing; the button itself is already disabled whenever that's
  // null, so a real call here always has a real folder to open.
  async function handleGoToSaveFolder(folder) {
    await openFolderNative(folder, (msg) => setSaveMeshesStatus(`Couldn't open the folder: ${msg}`));
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
        setLastSavedMeshesFolder(savedTo);
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
  // frontend_legacy/app.js's populateTemplateSelect.
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

  // the shipped cranial templates come in four variants - one per
  // (frontal landmark, CoM) combination - because each is built in that
  // exact registered frame. so unlike a remembered *preference*, which
  // frame is correct isn't the user's choice at all: ticking the 4th
  // landmark or toggling CoM changes which of the four is the only one
  // that will line up, and leaving the previous pick selected shows an
  // overlay that's visibly offset from a perfectly good registration.
  // switching automatically is the point.
  //
  // "custom" is left alone - if the user picked their own file, they mean
  // it, and there's no variant of it to switch to.
  useEffect(() => {
    if (shippedTemplates.length === 0) return;
    if (target !== "cranium" || selectedTemplate === "custom") return;
    const derived = defaultTemplateForTarget(target, useAltFrontal, comTranslation);
    if (derived === selectedTemplate) return;
    setSelectedTemplate(derived);
    localStorage.setItem(templateChoiceStorageKey(target), derived);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useAltFrontal, comTranslation, shippedTemplates]);

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
  //
  // also gated on being on the Preprocessing tab specifically - the
  // checkbox living there is a Preprocessing-workspace control, and its
  // state staying checked shouldn't make the template comparison bleed
  // into the Analysis workspace's own overlays (HC-line, heatmap, forehead
  // morphology, frontal bossing) once the user switches tabs. switching
  // back to Preprocessing with the checkbox still on re-shows it exactly
  // as it was, no re-toggle needed.
  useEffect(() => {
    async function refresh() {
      if (!showTemplateOverlay || !pipelineRan || activeWorkspace !== "preprocessing") {
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
  }, [
    showTemplateOverlay,
    pipelineRan,
    activeWorkspace,
    selectedTemplate,
    customTemplatePath,
    customTemplateBlobUrl,
    meshRevision,
  ]);

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

  // everything about the CURRENT target's preprocessing/analysis scene that
  // isn't already covered by another restore mechanism - selectedTemplate/
  // customTemplatePath/templateOffset are deliberately left out, since the
  // existing localStorage-backed effect (above) and the template-overlay
  // effect (below) already re-derive those from target on their own any
  // time it changes, snapshotting them here would just fight that. nicpParams
  // is a standing preference, not per-scene, so it's left alone too.
  //
  // alignSucceeded/landmarksChangedSinceAlign/registeredTransform/
  // adjustingInAlignedFrame/alignStatus are ALSO deliberately left out, for
  // a similar but stronger reason: landmarks are shared across targets (see
  // the landmarks state above), and register()'s core landmark-triangle fit
  // - the part registeredTransform actually captures - doesn't depend on
  // target at all (only an unrelated, purely-cosmetic recenter step
  // downstream of it does, for facial specifically - see
  // craniumpy_core.pipeline.register). so "aligned, landmarks unchanged" is
  // just as true after switching target as it was before - forcing the
  // user back through "align" again on every switch would be asking them
  // to redo something that's still valid. handleTargetChange below quietly
  // re-runs align (cheap - no repair/decimation, unlike clip/run) against
  // the new target when this holds, purely to keep the registered-mesh
  // preview accurate; align/adjust picks themselves stay exactly as they
  // were throughout, never flipping back to "not yet aligned".
  function captureTargetSnapshot() {
    return {
      meshStage: pipelineRan ? "result" : alignSucceeded ? "registered" : "original",
      showingNicpResult,
      nicpResultReady,
      pipelineRan,
      runStarted,
      runProgress,
      runStatus,
      runError,
      comTranslation,
      resampleMode,
      vertexCount,
      showTemplateOverlay,
      fittingTemplate,
      nicpFitStarted,
      nicpProgress,
      nicpStatus,
      nicpError,
      savingMeshes,
      saveMeshesStatus,
      lastSavedMeshesFolder,
      analysisResults,
      analysisStatus,
      analysisViewMode,
      exportingAnalysis,
      exportAnalysisStatus,
      exportCohortStatus,
      lastSavedAnalysisFolder,
    };
  }

  function applyTargetSnapshot(snapshot) {
    setPipelineRan(snapshot.pipelineRan);
    setRunStarted(snapshot.runStarted);
    setRunProgress(snapshot.runProgress);
    setRunStatus(snapshot.runStatus);
    setRunError(snapshot.runError);
    setComTranslation(snapshot.comTranslation);
    setResampleMode(snapshot.resampleMode);
    setVertexCount(snapshot.vertexCount);
    setShowTemplateOverlay(snapshot.showTemplateOverlay);
    setFittingTemplate(snapshot.fittingTemplate);
    setNicpFitStarted(snapshot.nicpFitStarted);
    setNicpProgress(snapshot.nicpProgress);
    setNicpStatus(snapshot.nicpStatus);
    setNicpError(snapshot.nicpError);
    setShowingNicpResult(snapshot.showingNicpResult);
    setNicpResultReady(snapshot.nicpResultReady);
    setSavingMeshes(snapshot.savingMeshes);
    setSaveMeshesStatus(snapshot.saveMeshesStatus);
    setLastSavedMeshesFolder(snapshot.lastSavedMeshesFolder);
    setAnalysisResults(snapshot.analysisResults);
    setAnalysisStatus(snapshot.analysisStatus);
    setAnalysisViewMode(snapshot.analysisViewMode);
    setExportingAnalysis(snapshot.exportingAnalysis);
    setExportAnalysisStatus(snapshot.exportAnalysisStatus);
    setExportCohortStatus(snapshot.exportCohortStatus);
    setLastSavedAnalysisFolder(snapshot.lastSavedAnalysisFolder);
  }

  // a target that's never been clipped/run this session - same "nothing
  // done yet" state resetPreprocessingState puts a fresh upload in, minus
  // the fields that aren't target-scoped (landmarks, the align state, saveDestDir, ...).
  function applyBlankTargetState() {
    setPipelineRan(false);
    setRunStarted(false);
    setRunProgress(0);
    setRunStatus("");
    setRunError(false);
    setShowTemplateOverlay(false);
    setFittingTemplate(false);
    setNicpFitStarted(false);
    setNicpProgress(0);
    setNicpStatus("");
    setNicpError(false);
    setShowingNicpResult(false);
    setNicpResultReady(false);
    setSavingMeshes(false);
    setSaveMeshesStatus("");
    setLastSavedMeshesFolder(null);
    setAnalysisResults(null);
    setAnalysisStatus("");
    setAnalysisViewMode("metopic");
    setExportingAnalysis(false);
    setExportAnalysisStatus("");
    setLastSavedAnalysisFolder(null);
    setExportCohortStatus("");
  }

  // snapshots the OLD target's scene, then either restores NEW target's own
  // snapshot (if both the frontend and the backend agree one exists) or
  // resets its clip/run state to blank - either way with zero
  // recomputation, no automatic re-running of clip/run. the backend's own
  // restored flag (see api/sessions.py's Session.switch_active_target) is
  // what actually decides which branch to take: the frontend snapshot
  // always exists exactly when the backend one does, since
  // handleTargetChange is the only place either gets written, but trusting
  // the backend keeps the two from ever being able to drift - the backend
  // fields are what save/export actually reads, so they're the ones that
  // matter.
  //
  // align is deliberately handled separately from both of those branches -
  // see captureTargetSnapshot's comment for why it isn't target-scoped at
  // all. a target that's otherwise blank still gets a quiet, cheap re-align
  // (no repair/decimation, unlike clip/run) when the landmarks that
  // produced alignSucceeded are still unchanged, purely to keep the
  // registered-mesh preview accurate for the new target - align/adjust
  // picks themselves never flip back to "not yet aligned" over this.
  async function handleTargetChange(newTarget) {
    if (newTarget === target) return;
    const oldTarget = target;
    const outgoingSnapshot = captureTargetSnapshot();
    setTargetSnapshots((prev) => ({ ...prev, [oldTarget]: outgoingSnapshot }));

    if (newTarget !== "cranium" && useAltFrontal) {
      setUseAltFrontal(false);
      setLandmarks((prev) => {
        const { [ALT_FRONTAL_NAME]: _drop, ...rest } = prev;
        return rest;
      });
      // the active landmark set just changed (4 points -> 3) - same as
      // handleUseAltFrontalChange dropping it directly, this makes the
      // quiet re-align below correctly sit out until the user re-aligns
      // themselves, instead of silently aligning a stale point set.
      setLandmarksChangedSinceAlign(true);
    }
    setTarget(newTarget);

    let restored = false;
    if (sessionId) {
      try {
        ({ restored } = await switchTarget(sessionId, newTarget));
      } catch {
        // no session yet, or the switch itself failed - fall through to the
        // blank-state branch below, same as a target that was never run.
      }
    }

    const incomingSnapshot = targetSnapshots[newTarget];
    if (restored && incomingSnapshot) {
      applyTargetSnapshot(incomingSnapshot);
      if (sessionId) {
        const descriptor = incomingSnapshot.showingNicpResult ? "nicp-result" : incomingSnapshot.meshStage;
        const neededKey = meshDisplayKey(sessionId, newTarget, descriptor);
        // skip the fetch/GLTF-parse/camera-refit entirely when what's
        // already on screen is already exactly this - e.g. toggling back
        // and forth without touching anything else in between.
        if (displayedMeshKeyRef.current !== neededKey) {
          await viewerRef.current.displayMesh(
            incomingSnapshot.showingNicpResult ? nicpResultMeshUrl(sessionId) : meshUrl(sessionId, incomingSnapshot.meshStage),
            { selectionHasTexture: incomingSnapshot.showingNicpResult ? false : selectionHasTexture },
          );
          displayedMeshKeyRef.current = neededKey;
        }
        setMeshRevision((n) => n + 1);
      }
      return;
    }

    applyBlankTargetState();
    if (!sessionId) return;

    if (alignSucceeded && !landmarksChangedSinceAlign) {
      // still-valid landmarks - re-register (fast) against the new target
      // rather than forcing the user through "align" again. handleAlign
      // itself handles the mesh reload/key-tracking and leaves
      // alignSucceeded true throughout.
      await handleAlign(newTarget);
      return;
    }

    // never aligned at all yet (or landmarks changed) - genuinely blank,
    // same plain original mesh a fresh upload starts on. if the target
    // being LEFT was also still in that state (the common "just exploring
    // the toggle" case before picking landmarks), this is a no-op: same
    // mesh already showing.
    const neededKey = meshDisplayKey(sessionId, newTarget, "original");
    if (displayedMeshKeyRef.current !== neededKey) {
      await viewerRef.current.displayMesh(meshUrl(sessionId, "original"), { selectionHasTexture });
      displayedMeshKeyRef.current = neededKey;
    }
    setMeshRevision((n) => n + 1);
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
    displayedMeshKeyRef.current = meshDisplayKey(sessionId, target, "original");
    setMeshRevision((n) => n + 1);
  }

  // targetOverride lets handleTargetChange trigger a quiet re-align against
  // the target it's switching TO before that target-change's own setTarget
  // call has actually committed - reading the target state directly here
  // would still see the OLD value (state setters don't update the current
  // closure synchronously), sending the wrong target to the backend.
  async function handleAlign(targetOverride) {
    const alignTarget = targetOverride ?? target;
    setAligning(true);
    setAlignStatus("Preparing...");
    try {
      await startAlign(sessionId, {
        target: alignTarget,
        landmarks: LANDMARK_NAMES.map((n) => landmarks[n]),
        altFrontalLandmark: useAltFrontal ? landmarks[ALT_FRONTAL_NAME] : undefined,
      });
      const result = await pollStatus(sessionId, (stage, detail) => {
        if (stage === "error") setAlignStatus(`Error: ${detail}`);
        else if (stage !== "done") setAlignStatus(describeStage(stage, detail));
      });
      if (result.status === "done") {
        await viewerRef.current.displayMesh(meshUrl(sessionId, "registered"), { selectionHasTexture });
        displayedMeshKeyRef.current = meshDisplayKey(sessionId, alignTarget, "registered");
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
        setRunStatus(describeStage(stage, detail));
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
        displayedMeshKeyRef.current = meshDisplayKey(sessionId, target, "result");
        setShowingNicpResult(false);
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
  // (session.nicp_result_mesh) - but once the fit's done, the viewer
  // switches to showing THAT mesh (see setShowingNicpResult below), since
  // that's the thing the user just asked to see. the Analysis-tab overlay
  // effect is what puts the patient's own result_mesh back once it's
  // actually needed (craniometrics/heatmap/metopic are all computed
  // against result_mesh, not the fit).
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
          : describeStage(stage, detail),
      );
    }

    try {
      await startRun(sessionId, { nVertices: null, nicp: nicpConfig });
      const result = await pollStatus(sessionId, onStage);
      if (result.status === "done") {
        setNicpProgress(100);
        setNicpStatus("Fit complete: ✓");
        // show the thing the user just fit, not the patient's own mesh
        // unchanged - this also tears down the live preview object (see
        // Viewer.jsx's displayMesh), so the finally block's own
        // hideNicpPreview call below becomes a harmless no-op for the
        // success path, same as it always was for the failure path.
        await viewerRef.current.displayMesh(nicpResultMeshUrl(sessionId), { selectionHasTexture: false });
        displayedMeshKeyRef.current = meshDisplayKey(sessionId, target, "nicp-result");
        setShowingNicpResult(true);
        setNicpResultReady(true);
        // land on just the fitted mesh, not a template comparison drawn on
        // top of it - if "compare to template" was checked, switch it back
        // off rather than re-showing it against the new result; the user
        // can turn it on again themselves if they want that. this also
        // covers the "mesh stuck looking like the deforming preview"
        // symptom the redraw-against-the-fit-result behavior could hit,
        // since there's now nothing left to redraw.
        setShowTemplateOverlay(false);
        viewerRef.current?.hideTemplateOverlay();
      }
    } catch (err) {
      setNicpError(true);
      setNicpStatus(`failed to start: ${err.message}`);
    } finally {
      nicpPollingRef.current = false;
      // the only place the fit's visualization (red wireframe+nodes
      // template, dimmed patient mesh) ever gets torn down - on failure
      // this is what puts the viewer back to showing the patient's own
      // mesh normally; on success, the displayMesh call above already tore
      // it down as part of loading the fit result, so this is a no-op by
      // the time it runs.
      viewerRef.current?.hideNicpPreview();
      setFittingTemplate(false);
      // on success, showTemplateOverlay was just switched off above, so
      // this bump just lets the compare-to-template effect (and anything
      // else keyed on meshRevision, e.g. the Analysis tab's overlays)
      // notice the mesh actually changed - not a redraw request.
      setMeshRevision((n) => n + 1);
    }
  }

  // PreprocessingPanel's "continue with NICP mesh" checkbox - only ever
  // reachable once nicpResultReady, so sessionId/the NICP mesh itself are
  // both guaranteed to exist. swaps the viewer immediately (this is what
  // makes it visible on the Preprocessing tab itself, not just next time
  // Analysis opens) - the Analysis-tab overlay effect below reads this
  // same state on its own next run (a fresh fetch, or a view-mode switch),
  // so the two never have to coordinate directly.
  async function handleUseNicpMeshChange(checked) {
    setShowingNicpResult(checked);
    const descriptor = checked ? "nicp-result" : "result";
    const neededKey = meshDisplayKey(sessionId, target, descriptor);
    if (displayedMeshKeyRef.current !== neededKey) {
      await viewerRef.current.displayMesh(
        checked ? nicpResultMeshUrl(sessionId) : meshUrl(sessionId, "result"),
        { selectionHasTexture: checked ? false : selectionHasTexture },
      );
      displayedMeshKeyRef.current = neededKey;
    }
    setMeshRevision((n) => n + 1);
  }

  // fetches craniometrics/asymmetry/metopic once a completed run exists and
  // the Analysis tab is actually open - re-fetches on meshRevision too, so
  // re-running the pipeline (target switch, a fresh NICP fit) with the tab
  // already open picks up the new numbers instead of showing stale ones.
  // resets analysisViewMode back to "metopic" (Forehead Morphology, the
  // default view) on every fresh fetch so a mode picked for a previous
  // session/run doesn't silently carry over.
  useEffect(() => {
    const onAnalysisTab = activeWorkspace === "analysis";
    if (!onAnalysisTab || !pipelineRan || !sessionId) {
      viewerRef.current?.hideMeasurementsOverlay();
      viewerRef.current?.hideHeatmap();
      viewerRef.current?.hideMetopicOverlay();
      viewerRef.current?.hideFrontalBossingOverlay();
      return;
    }
    let cancelled = false;
    (async () => {
      setAnalysisStatus("Loading...");
      try {
        const results = await getResults(sessionId);
        if (cancelled) return;
        setAnalysisResults(results);
        setAnalysisViewMode("metopic");
        setAnalysisStatus("");
      } catch (err) {
        if (!cancelled) setAnalysisStatus(`Failed to load results: ${err.message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace, pipelineRan, sessionId, meshRevision]);

  // drives the live viewer overlay to match whatever's currently loaded and
  // selected (HC-line/BPD/OFD for cranial, heatmap or the metopic contour
  // overlay for facial) - kept separate from the fetch above so toggling
  // AnalysisPanel's asymmetry/metopic switch swaps overlays immediately,
  // with no re-fetch needed.
  useEffect(() => {
    if (!analysisResults) return;
    (async () => {
      // mirrors AnalysisPanel.jsx's own showMeasurements/showAsymmetry/
      // showMetopic derivation exactly, so the live 3D overlay always
      // matches whatever the panel's numbers/mode-toggle are currently
      // showing. two different pairings can each need the toggle now -
      // cranial's own craniometrics+asymmetry, or facial's metopic+
      // asymmetry - see AnalysisPanel.jsx for why those are mutually
      // exclusive. the non-asymmetry side is the default view (see the
      // results-fetch effect above resetting to "metopic"), asymmetry only
      // shows once explicitly selected.
      const showModeToggle =
        (analysisResults.craniometrics && analysisResults.asymmetry) ||
        (analysisResults.metopic && analysisResults.asymmetry);
      const showAsymmetry = analysisResults.asymmetry && (!showModeToggle || analysisViewMode === "asymmetry");
      const showMeasurements = analysisResults.craniometrics && (!showModeToggle || analysisViewMode !== "asymmetry");
      const showMetopic = analysisResults.metopic && (!showModeToggle || analysisViewMode !== "asymmetry");

      // craniometrics/frontal-bossing/metopic overlays are plain 3D points/
      // lines, independent of the mesh's own vertex layout, so they read
      // correctly on either mesh - respect "continue with NICP mesh" (see
      // PreprocessingPanel.jsx, handleUseNicpMeshChange) for those. the
      // asymmetry heatmap can't: it's a literal per-VERTEX-INDEX color
      // array computed against result_mesh's own vertices (see
      // craniumpy_core.asymmetry), so it always needs result_mesh
      // specifically regardless of that checkbox - there's no valid way to
      // show a result_mesh-indexed heatmap on the NICP mesh's own, entirely
      // different vertex set.
      const wantNicpMesh = showingNicpResult && !showAsymmetry;
      const descriptor = wantNicpMesh ? "nicp-result" : "result";
      const neededKey = meshDisplayKey(sessionId, target, descriptor);
      if (displayedMeshKeyRef.current !== neededKey) {
        await viewerRef.current?.displayMesh(
          wantNicpMesh ? nicpResultMeshUrl(sessionId) : meshUrl(sessionId, "result"),
          { selectionHasTexture: wantNicpMesh ? false : selectionHasTexture },
        );
        displayedMeshKeyRef.current = neededKey;
      }

      viewerRef.current?.hideMeasurementsOverlay();
      viewerRef.current?.hideHeatmap();
      viewerRef.current?.hideMetopicOverlay();
      viewerRef.current?.hideFrontalBossingOverlay();
      if (showMeasurements) {
        viewerRef.current?.showMeasurementsOverlay({
          hcPolygon: analysisResults.craniometrics.hc_slice_polygon,
          frontOpt: analysisResults.craniometrics.front_opt,
          occOpt: analysisResults.craniometrics.occ_opt,
          lhOpt: analysisResults.craniometrics.lh_opt,
          rhOpt: analysisResults.craniometrics.rh_opt,
        });
      }
      if (showMetopic) {
        viewerRef.current?.showMetopicOverlay(analysisResults.metopic);
      } else if (showAsymmetry) {
        viewerRef.current?.showHeatmap(analysisResults.asymmetry.heatmap);
      }
      // not mutually exclusive with anything above except the asymmetry
      // heatmap specifically (see AnalysisPanel.jsx's showFrontalBossing) -
      // computed for both targets, shows alongside craniometrics/cranial
      // measurements or facial's Forehead Morphology overlay, just not the
      // plain asymmetry view.
      if (analysisResults.frontal_bossing && !showAsymmetry) {
        viewerRef.current?.showFrontalBossingOverlay(analysisResults.frontal_bossing);
      }
      // each show*Overlay call above just reset the mesh to its own default
      // opacity - apply the user's actual slider value on top of that.
      viewerRef.current?.setMeshOpacity(analysisMeshOpacity);
    })();
    // deliberately not deps of this effect (see handleAnalysisMeshOpacityChange
    // for the opacity one): dragging the opacity slider shouldn't rebuild the
    // whole overlay. showingNicpResult/sessionId/selectionHasTexture are
    // read fresh off the closure each run rather than watched directly -
    // this effect already re-runs on every natural trigger (a fresh fetch,
    // or a view-mode switch), so it never needs to coordinate with
    // handleUseNicpMeshChange (the other place showingNicpResult drives a
    // swap) beyond that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisResults, analysisViewMode]);

  function handleAnalysisMeshOpacityChange(value) {
    setAnalysisMeshOpacity(value);
    viewerRef.current?.setMeshOpacity(value);
  }

  // same desktop-first-then-bundle-download fallback as handleSaveMeshes.
  // patientMetadata rides along either way (POST body or GET query params -
  // see api/sessions.js's saveAnalysis/analysisBundleUrl); cohortPath only
  // on the desktop/POST path, since a one-shot zip download has nowhere
  // persistent to append a cohort row into.
  async function handleExportAnalysis() {
    setExportingAnalysis(true);
    setExportCohortStatus("");
    const exportSelection = { measurements: exportMeasurements, asymmetry: exportAsymmetry, meshes: exportMeshes };
    if (isDesktopApp()) {
      setExportAnalysisStatus("Exporting...");
      const targetCohortPath = cohortMode !== "none" ? cohortPath : null;
      try {
        const { saved_to: savedTo } = await saveAnalysis(
          sessionId, saveDestDir, patientMetadata, targetCohortPath, exportSelection,
        );
        setExportAnalysisStatus(`Saved to ${savedTo}`);
        setLastSavedAnalysisFolder(savedTo);
        if (targetCohortPath) {
          setExportCohortStatus(`added to cohort ${baseName(targetCohortPath)}: ${targetCohortPath}`);
        }
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
    window.location.href = analysisBundleUrl(sessionId, patientMetadata, exportSelection);
  }

  // what the viewer actually shows: raw picks on the raw mesh before
  // alignment, the same picks re-projected into the aligned frame while
  // either "adjust picks" is active or the secondary-frontal checkbox gets
  // ticked post-align with no 4th point picked yet (so there's something
  // to click against for that extra point), or nothing once aligned and
  // neither applies - this alone gives "remove landmarks after
  // registration, only show them when adjust (or an unplaced alt-frontal
  // pick) is toggled" with no separate hide/show bookkeeping. the
  // "!landmarks[ALT_FRONTAL_NAME]" half matters: without it, a session
  // that had all 4 landmarks (including alt-frontal) picked from the
  // start never hides them after align at all, since useAltFrontal alone
  // stays true forever once ticked - only the *unplaced* 4th-point case
  // needs the aligned markers kept visible as click targets. locked to
  // hidden again once the pipeline has run - landmark *positions* are
  // locked in at that point (align/adjust picks stay disabled); only
  // target/resample tuning can still trigger a re-run.
  const showAlignedLandmarks =
    alignSucceeded &&
    !pipelineRan &&
    (adjustingInAlignedFrame || (useAltFrontal && !landmarks[ALT_FRONTAL_NAME]));
  const displayLandmarks = !alignSucceeded
    ? landmarks
    : showAlignedLandmarks
      ? Object.fromEntries(Object.entries(landmarks).map(([n, p]) => [n, applyTransform(p, registeredTransform)]))
      : {};

  const onPreprocessingTab = activeWorkspace === "preprocessing";
  const onAnalysisTab = activeWorkspace === "analysis";
  const inspectorTitle = onPreprocessingTab ? "Preprocessing" : onAnalysisTab ? "Analysis" : "Data";

  if (appMode === "cohort") {
    return (
      <Shell
        appMode={appMode}
        onAppModeChange={setAppMode}
        workspaces={[]}
        workspace={<CohortWorkspace />}
        inspectorTitle={null}
        inspector={null}
      />
    );
  }

  if (appMode === "longitudinal") {
    return (
      <Shell
        appMode={appMode}
        onAppModeChange={setAppMode}
        workspaces={[]}
        workspace={<LongitudinalWorkspace />}
        inspectorTitle={null}
        inspector={null}
      />
    );
  }

  return (
    <Shell
      appMode={appMode}
      onAppModeChange={setAppMode}
      contextLabel={meshLabel}
      workspaces={WORKSPACES}
      activeWorkspace={activeWorkspace}
      onWorkspaceChange={setActiveWorkspace}
      inspectorTitle={inspectorTitle}
      metadataForm={
        sessionId != null && (
          <PatientMetadataForm
            metadata={patientMetadata}
            onFieldChange={handlePatientMetadataFieldChange}
            isDesktop={isDesktopApp()}
            cohortMode={cohortMode}
            cohortPath={cohortPath}
            onCohortModeChange={handleCohortModeChange}
            samePatientMode={samePatientMode}
            onSamePatientModeChange={setSamePatientMode}
          />
        )
      }
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
            onAlign={() => handleAlign()}
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
            nicpResultReady={nicpResultReady}
            useNicpMesh={showingNicpResult}
            onUseNicpMeshChange={handleUseNicpMeshChange}
            onSaveMeshes={handleSaveMeshes}
            savingMeshes={savingMeshes}
            saveMeshesStatus={saveMeshesStatus}
            saveDestDir={saveDestDir}
            onChooseSaveFolder={handleChooseSaveFolder}
            onUseDefaultSaveFolder={handleUseDefaultSaveFolder}
            savedMeshesFolder={lastSavedMeshesFolder}
            onGoToSaveFolder={handleGoToSaveFolder}
          />
        ) : onAnalysisTab ? (
          <AnalysisPanel
            pipelineRan={pipelineRan}
            analysisResults={analysisResults}
            analysisStatus={analysisStatus}
            analysisViewMode={analysisViewMode}
            onSetAnalysisViewMode={setAnalysisViewMode}
            analysisMeshOpacity={analysisMeshOpacity}
            onAnalysisMeshOpacityChange={handleAnalysisMeshOpacityChange}
            onExportAnalysis={handleExportAnalysis}
            exportingAnalysis={exportingAnalysis}
            exportAnalysisStatus={exportAnalysisStatus}
            exportCohortStatus={exportCohortStatus}
            exportMeasurements={exportMeasurements}
            onExportMeasurementsChange={setExportMeasurements}
            exportAsymmetry={exportAsymmetry}
            onExportAsymmetryChange={setExportAsymmetry}
            exportMeshes={exportMeshes}
            onExportMeshesChange={setExportMeshes}
            isDesktop={isDesktopApp()}
            saveDestDir={saveDestDir}
            onChooseSaveFolder={handleChooseSaveFolder}
            onUseDefaultSaveFolder={handleUseDefaultSaveFolder}
            savedAnalysisFolder={lastSavedAnalysisFolder}
            onGoToSaveFolder={handleGoToSaveFolder}
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
            onFilesDropped={!onPreprocessingTab && !onAnalysisTab ? handleFilesDropped : undefined}
          />
          {sessionId == null && !dropStatus && <p className="hint overlay">Upload a mesh to begin.</p>}
          {dropStatus && <p className="hint overlay">{dropStatus}</p>}
          {onAnalysisTab &&
            analysisResults?.asymmetry &&
            (!analysisResults?.metopic || analysisViewMode === "asymmetry") && (
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
