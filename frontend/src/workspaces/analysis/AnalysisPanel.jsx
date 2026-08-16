import SaveFolderControl from "../../components/SaveFolderControl.jsx";
import ProfileChart from "../../components/ProfileChart.jsx";
import InfoTooltip from "../../components/InfoTooltip.jsx";
import { MEASUREMENT_EXPLAINERS, GRAPH_EXPLAINERS, IDEAL_PARABOLA_EXPLAINER } from "../../lib/measurementExplainers.js";

// everything the 3 profile charts need, derived from one MetopicResult:
//  - phiIdeal/kappaIdeal: the same "ideal (parabola)" reference curves the
//    PDF report already draws (see api/results_bundle.py's _draw_metopic),
//    restated here so the live charts show the same comparison. parametrizing
//    the ideal parabola z = a*x^2 + c by its own x (rather than u/s) gives a
//    parametrization-invariant tangent angle/curvature - same derivation
//    _draw_metopic's own phi_ideal/kappa_ideal comment explains.
//    metopic.contour is index-aligned with normalized_arc_length/gradient_
//    profile/curvature_profile (all built from the same smoothed x/z/s
//    arrays server-side), so zipping by index is safe.
//  - bands: the central-ridge/left-temple/right-temple windows the table
//    above is actually computed from, for ProfileChart's shaded regions.
//  - domain: [lo, hi] in u, a bit wider than the temporal windows (the
//    outermost windows actually used) - everything past this is raw contour
//    with no window backing it, dominated by numerical-differentiation
//    noise right at the mesh's own clip boundary rather than real anatomy.
//    trimming the charts to this range keeps that edge noise from both
//    cluttering the picture and (worse) blowing out the y-scale so the
//    actually-meaningful central part reads as a flat line by comparison.
function metopicChartData(metopic) {
  const a = metopic.parabola_a;
  const slopes = metopic.contour.map((p) => 2 * a * p.x);
  const phiIdealFull = slopes.map((m) => Math.atan2(m, 1));
  const kappaIdealFull = slopes.map((m) => (-2 * a) / Math.pow(1 + m * m, 1.5));

  const [lt0] = metopic.left_temporal_window;
  const [, rt1] = metopic.right_temporal_window;
  const margin = 0.05;
  const lo = Math.max(0, lt0 - margin);
  const hi = Math.min(1, rt1 + margin);

  const u = metopic.normalized_arc_length;
  const keep = u.map((uv) => uv >= lo && uv <= hi);
  const clip = (arr) => arr.filter((_, i) => keep[i]);

  return {
    u: clip(u),
    gradient: clip(metopic.gradient_profile),
    curvature: clip(metopic.curvature_profile),
    deviation: clip(metopic.deviation_profile),
    phiIdeal: clip(phiIdealFull),
    kappaIdeal: clip(kappaIdealFull),
    bands: [
      { x0: metopic.central_window[0], x1: metopic.central_window[1], color: "#d1453d" },
      { x0: metopic.left_temporal_window[0], x1: metopic.left_temporal_window[1], color: "#0891b2" },
      { x0: metopic.right_temporal_window[0], x1: metopic.right_temporal_window[1], color: "#0891b2" },
    ],
  };
}

// cephalometric measurements + asymmetry index (cranial) or asymmetry
// index + metopic/frontal-angle shape (facial), read straight from GET
// /results - App.jsx owns the fetch and the matching live viewer overlay
// (HC-line/BPD/OFD, the asymmetry heatmap, or the metopic contour
// overlay), this is just the numbers + the export button. either target's
// results can carry both its own "primary" view and asymmetry together
// (see craniumpy_core.asymmetry's module docstring) - when both are
// present, analysisViewMode/onSetAnalysisViewMode (owned by App.jsx, since
// it also drives which viewer overlay is showing) pick between them.
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
  exportCohortStatus,
  exportMeasurements,
  onExportMeasurementsChange,
  exportAsymmetry,
  onExportAsymmetryChange,
  exportMeshes,
  onExportMeshesChange,
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
  // two different pairings can each need a toggle: cranial's own
  // craniometrics+asymmetry, or facial's metopic+asymmetry - craniometrics
  // and metopic are mutually exclusive (cranial-only/facial-only
  // respectively), so at most one of these is ever true for a given
  // session.
  const showModeToggle = (craniometrics && asymmetry) || (metopic && asymmetry);
  const showAsymmetry = asymmetry && (!showModeToggle || analysisViewMode === "asymmetry");
  const showMeasurements = craniometrics && (!showModeToggle || analysisViewMode !== "asymmetry");
  const showMetopic = metopic && (!showModeToggle || analysisViewMode !== "asymmetry");
  // frontal bossing isn't part of either target's "asymmetry" view - keep
  // it out of that view (a session with no mode toggle at all is
  // unaffected here; otherwise it shows alongside whichever of
  // measurements/forehead morphology is currently active).
  const showFrontalBossing = frontalBossing && !showAsymmetry;

  const chartData = showMetopic ? metopicChartData(metopic) : null;

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

      {showMeasurements && (
        <>
          <p className="hint">HC ring (red), BPD (blue), OFD (green) drawn live on the mesh.</p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>
                  OFD (depth)
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.depthMm} />
                </th>
                <td>{craniometrics.depth_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>
                  BPD (breadth)
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.breadthMm} />
                </th>
                <td>{craniometrics.breadth_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>
                  Cephalic index
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.cephalicIndex} />
                </th>
                <td>{craniometrics.cephalic_index.toFixed(1)}</td>
              </tr>
              <tr>
                <th>
                  Head circumference
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.circumferenceCm} />
                </th>
                <td>{craniometrics.circumference_cm.toFixed(1)} cm</td>
              </tr>
              <tr>
                <th>
                  Volume
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.meshVolumeCc} />
                </th>
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
                <th>
                  Frontal bossing angle
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.frontalBossingAngle} />
                </th>
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
            {craniometrics ? "Cranial Measurements" : "Forehead Morphology"}
          </button>
          <button
            type="button"
            className={analysisViewMode === "asymmetry" ? "active" : ""}
            onClick={() => onSetAnalysisViewMode("asymmetry")}
          >
            {craniometrics ? "Cranial Asymmetry" : "Facial Asymmetry"}
          </button>
        </div>
      )}

      {showAsymmetry && (
        <>
          <p className="hint">asymmetry heatmap - blue (dented) / red (protruded), drawn live on the mesh.</p>
          <table className="measurements-table">
            <tbody>
              <tr>
                <th>
                  Mean asymmetry index
                  <InfoTooltip
                    text={craniometrics ? MEASUREMENT_EXPLAINERS.cranialAsymmetryIndex : MEASUREMENT_EXPLAINERS.facialAsymmetryIndex}
                  />
                </th>
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
                <th>
                  Frontal angle
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.frontalAngleDeg} />
                </th>
                <td>{metopic.frontal_angle_deg.toFixed(1)}&deg;</td>
              </tr>
              <tr>
                <th>
                  Midline curvature concentration
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.midlineCurvatureConcentration} />
                </th>
                <td>{metopic.midline_curvature_concentration.toFixed(2)}</td>
              </tr>
              <tr>
                <th>
                  Ridge protrusion
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.ridgeProtrusion} />
                </th>
                <td>{metopic.ridge_protrusion_mm.toFixed(1)} mm</td>
              </tr>
              <tr>
                <th>
                  Ridge area
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.ridgeArea} />
                </th>
                <td>
                  {metopic.ridge_area_mm2.toFixed(0)} mm&sup2; ({metopic.ridge_area_normalized.toFixed(3)} norm.)
                </td>
              </tr>
              <tr>
                <th>
                  Temporal hollowing (L / R)
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.temporalHollowing} />
                </th>
                <td>
                  {metopic.left_temporal_hollowing.toFixed(3)} / {metopic.right_temporal_hollowing.toFixed(3)}
                </td>
              </tr>
              <tr>
                <th>
                  Max temporal depth (L / R)
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.maxTemporalDepth} />
                </th>
                <td>
                  {metopic.left_max_temporal_depth_mm.toFixed(1)} / {metopic.right_max_temporal_depth_mm.toFixed(1)} mm
                </td>
              </tr>
              <tr>
                <th>
                  Parabolic deviation index
                  <InfoTooltip text={MEASUREMENT_EXPLAINERS.parabolicDeviationIndex} />
                </th>
                <td>{metopic.parabolic_deviation_index.toFixed(2)} mm</td>
              </tr>
            </tbody>
          </table>

          <p className="hint metopic-parabola-note">{IDEAL_PARABOLA_EXPLAINER}</p>

          <ProfileChart
            title="gradient / tangent angle - phi(u)"
            explainer={GRAPH_EXPLAINERS.gradient}
            x={chartData.u}
            y={chartData.gradient}
            referenceY={chartData.phiIdeal}
            bands={chartData.bands}
            color="var(--bpd)"
          />
          <ProfileChart
            title="signed curvature - kappa(u)"
            explainer={GRAPH_EXPLAINERS.curvature}
            x={chartData.u}
            y={chartData.curvature}
            referenceY={chartData.kappaIdeal}
            bands={chartData.bands}
            color="var(--ofd)"
          />
          <ProfileChart
            title="deviation from parabola - d_P(u)"
            explainer={GRAPH_EXPLAINERS.deviation}
            x={chartData.u}
            y={chartData.deviation}
            bands={chartData.bands}
            color="var(--hc)"
            zeroLine
          />
        </>
      )}

      <div className="toggle-row">
        <label className="checkbox">
          <input type="checkbox" checked={exportMeasurements} onChange={(e) => onExportMeasurementsChange(e.target.checked)} />
          measurements
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={exportAsymmetry} onChange={(e) => onExportAsymmetryChange(e.target.checked)} />
          asymmetry
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={exportMeshes} onChange={(e) => onExportMeshesChange(e.target.checked)} />
          meshes
        </label>
      </div>
      <button type="button" onClick={onExportAnalysis} disabled={exportingAnalysis}>
        export analysis
      </button>
      <p className="status-line">{exportAnalysisStatus}</p>
      {exportCohortStatus && <p className="status-line">{exportCohortStatus}</p>}
      <SaveFolderControl
        isDesktop={isDesktop}
        saveDestDir={saveDestDir}
        onChooseSaveFolder={onChooseSaveFolder}
        onUseDefaultSaveFolder={onUseDefaultSaveFolder}
      />
    </section>
  );
}
