import SaveFolderControl from "../../components/SaveFolderControl.jsx";
import ProfileChart from "../../components/ProfileChart.jsx";

// cephalometric measurements (cranial) or asymmetry index + metopic/
// frontal-angle shape (facial), read straight from GET /results - App.jsx
// owns the fetch and the matching live viewer overlay (HC-line/BPD/OFD,
// the asymmetry heatmap, or the metopic contour overlay), this is just the
// numbers + the export button. facial results can carry both asymmetry and
// metopic together (see craniumpy_core.metopic's module docstring) - when
// both are present, analysisViewMode/onSetAnalysisViewMode (owned by
// App.jsx, since it also drives which viewer overlay is showing) pick
// between them.
export default function AnalysisPanel({
  pipelineRan,
  analysisResults,
  analysisStatus,
  analysisViewMode,
  onSetAnalysisViewMode,
  analysisMeshOpacity,
  onAnalysisMeshOpacityChange,
  onExportAnalysis,
  exportingAnalysis,
  exportAnalysisStatus,
  isDesktop,
  saveDestDir,
  onChooseSaveFolder,
  onUseDefaultSaveFolder,
}) {
  if (!pipelineRan) {
    return <p className="hint">Run the pipeline in Preprocessing first.</p>;
  }
  if (analysisStatus) {
    return <p className="status-line">{analysisStatus}</p>;
  }
  if (!analysisResults) return null;

  const { craniometrics, asymmetry, metopic, frontal_bossing: frontalBossing } = analysisResults;
  const showModeToggle = asymmetry && metopic;
  const showAsymmetry = asymmetry && (!showModeToggle || analysisViewMode === "asymmetry");
  const showMetopic = metopic && (!showModeToggle || analysisViewMode !== "asymmetry");
  // frontal bossing isn't part of "facial asymmetry" - keep it out of that
  // view (cranial has no mode toggle at all, so it's unaffected there; on
  // facial it still shows under Forehead Morphology, where it belongs).
  const showFrontalBossing = frontalBossing && !showAsymmetry;

  return (
    <section>
      {(craniometrics || asymmetry || metopic || frontalBossing) && (
        <div className="opacity-slider">
          <label htmlFor="analysis-mesh-opacity">mesh opacity: {analysisMeshOpacity.toFixed(2)}</label>
          <input
            id="analysis-mesh-opacity"
            type="range"
            min="0.05"
            max="1"
            step="0.05"
            value={analysisMeshOpacity}
            onChange={(e) => onAnalysisMeshOpacityChange(parseFloat(e.target.value))}
          />
        </div>
      )}

      {craniometrics && (
        <>
          <p className="hint">HC ring (red), BPD (blue), OFD (green) drawn live on the mesh.</p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>OFD (depth)</th>
                <td>{craniometrics.depth_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>BPD (breadth)</th>
                <td>{craniometrics.breadth_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>Cephalic index</th>
                <td>{craniometrics.cephalic_index.toFixed(1)}</td>
              </tr>
              <tr>
                <th>Head circumference</th>
                <td>{craniometrics.circumference_cm.toFixed(1)} cm</td>
              </tr>
              <tr>
                <th>Volume</th>
                <td>{craniometrics.mesh_volume_cc.toFixed(1)} cc</td>
              </tr>
            </tbody>
          </table>
        </>
      )}

      {showFrontalBossing && (
        <>
          <p className="hint">
            frontal bossing - sellion to forehead-point angle (orange), drawn live on the mesh.
          </p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>Frontal bossing angle</th>
                <td>{frontalBossing.angle_deg.toFixed(1)}&deg;</td>
              </tr>
            </tbody>
          </table>
        </>
      )}

      {showModeToggle && (
        <div className="mode-toggle">
          <button
            type="button"
            className={analysisViewMode !== "asymmetry" ? "active" : ""}
            onClick={() => onSetAnalysisViewMode("metopic")}
          >
            Forehead Morphology
          </button>
          <button
            type="button"
            className={analysisViewMode === "asymmetry" ? "active" : ""}
            onClick={() => onSetAnalysisViewMode("asymmetry")}
          >
            Facial Asymmetry
          </button>
        </div>
      )}

      {showAsymmetry && (
        <>
          <p className="hint">asymmetry heatmap - blue (dented) / red (protruded), drawn live on the mesh.</p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>Mean asymmetry index</th>
                <td>{asymmetry.mean_asymmetry_index.toFixed(2)} mm</td>
              </tr>
            </tbody>
          </table>
        </>
      )}

      {showMetopic && (
        <>
          <p className="hint">
            forehead contour at the HC slice height - fitted parabola (blue), central ridge (red), temporal regions
            (teal), frontal angle construction (green) drawn live on the mesh.
          </p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>Frontal angle</th>
                <td>{metopic.frontal_angle_deg.toFixed(1)}&deg;</td>
              </tr>
              <tr>
                <th>Midline curvature concentration</th>
                <td>{metopic.midline_curvature_concentration.toFixed(2)}</td>
              </tr>
              <tr>
                <th>Ridge protrusion</th>
                <td>{metopic.ridge_protrusion_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>Ridge area</th>
                <td>
                  {metopic.ridge_area_mm2.toFixed(0)} mm&sup2; ({metopic.ridge_area_normalized.toFixed(3)} norm.)
                </td>
              </tr>
              <tr>
                <th>Temporal hollowing (L / R)</th>
                <td>
                  {metopic.left_temporal_hollowing.toFixed(3)} / {metopic.right_temporal_hollowing.toFixed(3)}
                </td>
              </tr>
              <tr>
                <th>Max temporal depth (L / R)</th>
                <td>
                  {metopic.left_max_temporal_depth_mm.toFixed(1)} / {metopic.right_max_temporal_depth_mm.toFixed(1)} mm
                </td>
              </tr>
              <tr>
                <th>Parabolic deviation index</th>
                <td>{metopic.parabolic_deviation_index.toFixed(2)} mm</td>
              </tr>
            </tbody>
          </table>
          <ProfileChart
            title="gradient / tangent angle - phi(u)"
            x={metopic.normalized_arc_length}
            y={metopic.gradient_profile}
            color="var(--bpd)"
          />
          <ProfileChart
            title="signed curvature - kappa(u)"
            x={metopic.normalized_arc_length}
            y={metopic.curvature_profile}
            color="var(--ofd)"
          />
          <ProfileChart
            title="deviation from parabola - d_P(u)"
            x={metopic.normalized_arc_length}
            y={metopic.deviation_profile}
            color="var(--hc)"
            zeroLine
          />
        </>
      )}

      <button type="button" onClick={onExportAnalysis} disabled={exportingAnalysis}>
        export analysis
      </button>
      <p className="status-line">{exportAnalysisStatus}</p>
      <SaveFolderControl
        isDesktop={isDesktop}
        saveDestDir={saveDestDir}
        onChooseSaveFolder={onChooseSaveFolder}
        onUseDefaultSaveFolder={onUseDefaultSaveFolder}
      />
    </section>
  );
}
