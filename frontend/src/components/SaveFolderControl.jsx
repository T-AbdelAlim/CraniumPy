// desktop-only override for where a save/export action writes - shown next
// to "save meshes"/"export analysis" in both PreprocessingPanel and
// AnalysisPanel, sharing one destination choice (App.jsx's saveDestDir).
// null means the default (next to the original mesh file, resolved
// entirely on the backend - see api/schemas.py's SaveRequest.dest_dir).
// renders nothing in browser mode - there's no real folder a browser tab
// can write into, so the whole idea of "picking a folder" doesn't apply.
export default function SaveFolderControl({ isDesktop, saveDestDir, onChooseSaveFolder, onUseDefaultSaveFolder }) {
  if (!isDesktop) return null;
  return (
    <>
      <p className="hint">save to: {saveDestDir || "next to the original mesh file"}</p>
      <div className="toggle-row">
        <button type="button" className="button-subtle" onClick={onChooseSaveFolder}>
          change save folder...
        </button>
        {saveDestDir && (
          <button type="button" className="button-subtle" onClick={onUseDefaultSaveFolder}>
            use default location
          </button>
        )}
      </div>
    </>
  );
}
