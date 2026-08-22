import { useState } from "react";
import { LANDMARK_LABELS, LANDMARK_DESCRIPTIONS, activeLandmarkNames } from "../../lib/landmarks.js";
import SaveFolderControl from "../../components/SaveFolderControl.jsx";
import InfoTooltip from "../../components/InfoTooltip.jsx";
import { MEASUREMENT_EXPLAINERS } from "../../lib/measurementExplainers.js";

// plain monochrome silhouettes (currentColor, so they theme with
// light/dark automatically) - deliberately not a real render/screenshot of
// a clipped mesh, to stay consistent with this app's own dependency-light
// approach (no image-asset pipeline for a decorative icon).
function CranialVaultIcon() {
  return (
    <svg viewBox="0 0 48 48" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M8 34 Q8 10 24 8 Q40 10 40 34" strokeLinecap="round" />
      <line x1="8" y1="34" x2="40" y2="34" />
    </svg>
  );
}

function FaceIcon() {
  return (
    <svg viewBox="0 0 48 48" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <ellipse cx="24" cy="24" rx="14" ry="18" />
      <line x1="24" y1="10" x2="24" y2="38" strokeDasharray="2 3" />
      <circle cx="18" cy="20" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="30" cy="20" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

// plain-language "what can I measure here" text for each region's hover
// icon, built from the same explainer copy the Analysis workspace's own
// InfoTooltips already use (frontend/src/lib/measurementExplainers.js) -
// one source of truth for what a metric means, reused instead of writing
// new copy.
const CRANIUM_METRICS_TEXT = [
  MEASUREMENT_EXPLAINERS.depthMm,
  MEASUREMENT_EXPLAINERS.breadthMm,
  MEASUREMENT_EXPLAINERS.cephalicIndex,
  MEASUREMENT_EXPLAINERS.circumferenceCm,
  MEASUREMENT_EXPLAINERS.cranialAsymmetryIndex,
  MEASUREMENT_EXPLAINERS.frontalBossingAngle,
].join(" ");

const FACE_METRICS_TEXT = [
  MEASUREMENT_EXPLAINERS.facialAsymmetryIndex,
  MEASUREMENT_EXPLAINERS.frontalAngleDeg,
  MEASUREMENT_EXPLAINERS.ridgeProtrusion,
  MEASUREMENT_EXPLAINERS.temporalHollowing,
  MEASUREMENT_EXPLAINERS.parabolicDeviationIndex,
].join(" ");

export default function PreprocessingPanel({
  target,
  onTargetChange,
  useAltFrontal,
  onUseAltFrontalChange,
  landmarks,
  alignSucceeded,
  landmarksChangedSinceAlign,
  aligning,
  pipelineRan,
  alignStatus,
  onAlign,
  onAdjustPicks,
  onReset,
  comTranslation,
  onComTranslationChange,
  resampleMode,
  onResampleModeChange,
  vertexCount,
  onVertexCountChange,
  nicpParams,
  onNicpParamsChange,
  onRunPipeline,
  runningPipeline,
  runStarted,
  runProgress,
  runStatus,
  runError,
  shippedTemplates,
  showTemplateOverlay,
  onShowTemplateOverlayChange,
  selectedTemplate,
  onTemplateChange,
  isDesktop,
  customTemplatePath,
  customTemplateName,
  onCustomTemplateBrowse,
  onCustomTemplateFile,
  templateOffset,
  templateStatus,
  onFitTemplate,
  fittingTemplate,
  nicpFitStarted,
  nicpProgress,
  nicpStatus,
  nicpError,
  nicpResultReady,
  useNicpMesh,
  onUseNicpMeshChange,
  onStageForLongitudinal,
  saveMeshesStatus,
  saveDestDir,
  onChooseSaveFolder,
  onUseDefaultSaveFolder,
  savedMeshesFolder,
  onGoToSaveFolder,
}) {
  const names = activeLandmarkNames(useAltFrontal);
  const allPicked = names.every((n) => n in landmarks);
  const alignDisabled = !allPicked || !landmarksChangedSinceAlign || aligning || pipelineRan;
  const adjustDisabled = !alignSucceeded || pipelineRan;
  // landmark positions lock in once a run has completed (align/adjust
  // picks stay disabled above), but target/com-translation/resample are
  // still fair game to tweak and re-run without redoing the align step -
  // /clip and /run always re-derive registration fresh from the current
  // landmarks + target, so there's nothing stale to invalidate here.
  const runDisabled = !alignSucceeded || landmarksChangedSinceAlign || runningPipeline;
  const [showNicpAdvanced, setShowNicpAdvanced] = useState(false);
  const [stageTimepoint, setStageTimepoint] = useState("t0");
  const [stagedNote, setStagedNote] = useState("");

  function handleStage() {
    onStageForLongitudinal(stageTimepoint);
    setStagedNote(`staged as ${stageTimepoint} (${target})`);
  }

  function renderItem(name) {
    const p = landmarks[name];
    return (
      <li key={name} data-name={name} className={p ? "picked" : ""}>
        <span className="landmark-swatch" />
        <span className="landmark-label">{LANDMARK_LABELS[name]}</span>
        <span className="landmark-sep"> | </span>
        <span className="landmark-desc">{LANDMARK_DESCRIPTIONS[name]}</span>
        <span className="landmark-value">{p ? `${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}` : "not picked"}</span>
      </li>
    );
  }

  return (
    <section>
      <p className="target-picker-header">interested in:</p>
      <div className="target-card-row">
        <label className={target === "cranium" ? "target-card active" : "target-card"}>
          <input
            type="radio"
            name="target"
            checked={target === "cranium"}
            onChange={() => onTargetChange("cranium")}
            className="visually-hidden"
          />
          <CranialVaultIcon />
          <span className="target-card-title">Cranial Vault</span>
          <span className="target-card-teaser">OFD, BPD, cephalic index, HC...</span>
          <InfoTooltip text={CRANIUM_METRICS_TEXT} />
        </label>
        <label className={target === "face" ? "target-card active" : "target-card"}>
          <input
            type="radio"
            name="target"
            checked={target === "face"}
            onChange={() => onTargetChange("face")}
            className="visually-hidden"
          />
          <FaceIcon />
          <span className="target-card-title">Face &amp; Forehead</span>
          <span className="target-card-teaser">Facial asymmetry, forehead shape...</span>
          <InfoTooltip text={FACE_METRICS_TEXT} />
        </label>
      </div>

      <p className="hint">
        <strong>ctrl/cmd-click</strong> to place a point, <strong>alt-drag</strong> to move one. Pick in this order:
      </p>
      <ol id="landmark-list">{names.map(renderItem)}</ol>
      {target === "cranium" && (
        <label className="checkbox">
          <input type="checkbox" checked={useAltFrontal} onChange={(e) => onUseAltFrontalChange(e.target.checked)} />
          use a secondary frontal landmark (e.g. subnasale) for the displayed/saved mesh
        </label>
      )}

      <div className="toggle-row">
        <button type="button" onClick={onAlign} disabled={alignDisabled}>
          align
        </button>
        <button type="button" onClick={onAdjustPicks} disabled={adjustDisabled}>
          adjust picks
        </button>
        <button type="button" onClick={onReset}>
          reset
        </button>
      </div>
      <p className="status-line">{alignStatus}</p>

      <label className="checkbox">
        <input type="checkbox" checked={comTranslation} onChange={(e) => onComTranslationChange(e.target.checked)} />
        center-of-mass correction
      </label>

      <p className="hint">finalize the mesh:</p>
      <label className="checkbox">
        <input type="radio" name="resample-mode" checked={resampleMode === "none"} onChange={() => onResampleModeChange("none")} />
        no resampling
      </label>
      <label className="checkbox">
        <input
          type="radio"
          name="resample-mode"
          checked={resampleMode === "resample"}
          onChange={() => onResampleModeChange("resample")}
        />
        resample to{" "}
        <input
          id="vertex-count"
          type="number"
          min="500"
          max="200000"
          step="500"
          value={vertexCount}
          disabled={resampleMode !== "resample"}
          onChange={(e) => onVertexCountChange(Number(e.target.value) || 10000)}
        />{" "}
        vertices
      </label>

      <button type="button" onClick={onRunPipeline} disabled={runDisabled}>
        preprocess mesh
      </button>
      {runStarted && (
        <>
          <div className={runError ? "progress-bar error" : "progress-bar"}>
            <div className="progress-bar-fill" style={{ width: `${runProgress}%` }} />
          </div>
          <p className="progress-label">{runStatus}</p>
        </>
      )}

      {/* only reachable once "preprocess mesh" has actually completed - a
          template comparison (or a fit) against the bare /align-only mesh
          would be comparing against something before its CoM correction,
          repair, and clip ever ran, which is misleading. */}
      {pipelineRan && (
        <>
          <p className="hint">compare against / fit a reference template:</p>
          <div className="template-controls">
            <select value={selectedTemplate} onChange={(e) => onTemplateChange(e.target.value)}>
              {shippedTemplates.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.description}
                </option>
              ))}
              <option value="custom">custom template...</option>
            </select>
            {selectedTemplate === "custom" &&
              (isDesktop ? (
                <div className="toggle-row">
                  <button type="button" onClick={onCustomTemplateBrowse}>
                    browse...
                  </button>
                  <span className="hint">
                    {customTemplatePath ? customTemplatePath.split(/[\\/]/).pop() : "no file picked yet"}
                  </span>
                </div>
              ) : (
                <>
                  <input
                    type="file"
                    accept=".ply,.obj,.stl,.glb,.gltf"
                    onChange={(e) => onCustomTemplateFile(e.target.files[0])}
                  />
                  <p className="hint">{customTemplateName || "no file picked yet (won't be remembered next time)"}</p>
                  <p className="hint">a browser-uploaded custom template can only be used for the overlay, not for fitting - pick a shipped one to fit against instead.</p>
                </>
              ))}
          </div>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={showTemplateOverlay}
              onChange={(e) => onShowTemplateOverlayChange(e.target.checked)}
            />
            compare to template
          </label>
          {templateStatus && <p className="status-line">{templateStatus}</p>}
          {templateOffset && (
            <p className="hint">
              center-of-gravity offset from template: {templateOffset.total.toFixed(1)}mm total (x{" "}
              {templateOffset.x.toFixed(1)}, y {templateOffset.y.toFixed(1)}, z {templateOffset.z.toFixed(1)})
            </p>
          )}

          <button type="button" className="disclosure-toggle" onClick={() => setShowNicpAdvanced((v) => !v)}>
            {showNicpAdvanced ? "hide" : "show"} advanced fit parameters
          </button>
          {showNicpAdvanced && (
            <div className="template-controls">
              <label htmlFor="nicp-alpha-start">stiffness start</label>
              <input
                id="nicp-alpha-start"
                type="number"
                step="1"
                value={nicpParams.alphaStart}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, alphaStart: Number(e.target.value) || 0 })}
              />
              <label htmlFor="nicp-alpha-end">stiffness end</label>
              <input
                id="nicp-alpha-end"
                type="number"
                step="1"
                value={nicpParams.alphaEnd}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, alphaEnd: Number(e.target.value) || 0 })}
              />
              <label htmlFor="nicp-alpha-steps">stiffness steps</label>
              <input
                id="nicp-alpha-steps"
                type="number"
                min="1"
                step="1"
                value={nicpParams.alphaSteps}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, alphaSteps: Number(e.target.value) || 1 })}
              />
              <label htmlFor="nicp-gamma">gamma</label>
              <input
                id="nicp-gamma"
                type="number"
                step="0.1"
                value={nicpParams.gamma}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, gamma: Number(e.target.value) || 0 })}
              />
              <label htmlFor="nicp-dist-threshold">distance threshold (mm)</label>
              <input
                id="nicp-dist-threshold"
                type="number"
                step="0.5"
                value={nicpParams.distThreshold}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, distThreshold: Number(e.target.value) || 0 })}
              />
              <label htmlFor="nicp-inner-iters">inner iterations</label>
              <input
                id="nicp-inner-iters"
                type="number"
                min="1"
                step="1"
                value={nicpParams.innerIters}
                onChange={(e) => onNicpParamsChange({ ...nicpParams, innerIters: Number(e.target.value) || 1 })}
              />
            </div>
          )}
          <p className="hint">
            interested in Longitudinal analysis (comparing this patient across timepoints)? point correspondence
            requires a NICP fit - stage this mesh for Longitudinal once the fit below completes.
          </p>
          <button type="button" onClick={onFitTemplate} disabled={fittingTemplate}>
            fit template (NICP) - same topology across every patient
          </button>
          {nicpFitStarted && (
            <>
              <div className={nicpError ? "progress-bar error" : "progress-bar"}>
                <div className="progress-bar-fill" style={{ width: `${nicpProgress}%` }} />
              </div>
              <p className="progress-label">{nicpStatus}</p>
            </>
          )}
          {nicpResultReady && (
            <>
              <label className="checkbox">
                <input type="checkbox" checked={useNicpMesh} onChange={(e) => onUseNicpMeshChange(e.target.checked)} />
                continue with the NICP-fitted mesh in the viewer (including Analysis)
              </label>
              {useNicpMesh && (
                <p className="hint">
                  the Asymmetry heatmap always shows on the original mesh regardless - it's colored per-vertex, which
                  doesn't carry over to the NICP-fitted mesh's own, different vertex layout.
                </p>
              )}
              <div className="stage-longitudinal-control">
                <label>
                  timepoint:
                  <select value={stageTimepoint} onChange={(e) => setStageTimepoint(e.target.value)}>
                    {["t0", "t1", "t2", "t3", "t4", "t5"].map((tp) => (
                      <option key={tp} value={tp}>
                        {tp}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" onClick={handleStage}>
                  stage for Longitudinal
                </button>
                {stagedNote && <p className="hint">{stagedNote}</p>}
              </div>
            </>
          )}

          {/* meshes save automatically after Align/Preprocess Mesh/NICP fit
              (see App.jsx's autoSaveMeshes) - this just shows where the last
              one landed, and lets the destination be redirected. */}
          <p className="status-line">{saveMeshesStatus}</p>
          <SaveFolderControl
            isDesktop={isDesktop}
            saveDestDir={saveDestDir}
            onChooseSaveFolder={onChooseSaveFolder}
            onUseDefaultSaveFolder={onUseDefaultSaveFolder}
            savedLocation={savedMeshesFolder}
            onGoToSaveFolder={onGoToSaveFolder}
          />
        </>
      )}
    </section>
  );
}
