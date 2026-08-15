import SaveFolderControl from "../../components/SaveFolderControl.jsx";

// cephalometric measurements (cranial) or asymmetry index (facial), read
// straight from GET /results - App.jsx owns the fetch and the matching
// live viewer overlay (HC-line/BPD/OFD or the heatmap), this is just the
// numbers + the export button.
export default function AnalysisPanel({
  pipelineRan,
  analysisResults,
  analysisStatus,
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

  const { craniometrics, asymmetry } = analysisResults;

  return (
    <section>
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

      {asymmetry && (
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
