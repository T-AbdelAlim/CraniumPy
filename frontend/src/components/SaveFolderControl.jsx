// desktop-only override for where a save/export action writes - shown next
// to "save meshes"/"export analysis" in both PreprocessingPanel and
// AnalysisPanel, sharing one destination choice (App.jsx's saveDestDir).
// null means the default (next to the original mesh file, resolved
// entirely on the backend - see api/schemas.py's SaveRequest.dest_dir).
// renders nothing in browser mode - there's no real folder a browser tab
// can write into, so the whole idea of "picking a folder" doesn't apply.
//
// savedLocation is the REAL folder the last save/export actually wrote to
// (the backend's own "saved_to", see App.jsx's handleSaveMeshes/
// handleExportAnalysis) - not saveDestDir, which is just the override
// choice and can drift from where a past save actually landed (e.g. the
// user picks a different folder AFTER already saving once). "go to save
// folder" always renders (per its own name, it should always be findable
// in the same spot) but stays disabled until there's a real location to
// open - nothing's been saved this session/target yet otherwise.
export default function SaveFolderControl({
  isDesktop,
  saveDestDir,
  onChooseSaveFolder,
  onUseDefaultSaveFolder,
  savedLocation,
  onGoToSaveFolder,
}) {
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
      <button
        type="button"
        className="button-subtle"
        onClick={() => onGoToSaveFolder(savedLocation)}
        disabled={!savedLocation}
        title={savedLocation ? `Open ${savedLocation}` : "Nothing saved here yet"}
      >
        go to save folder
      </button>
    </>
  );
}
