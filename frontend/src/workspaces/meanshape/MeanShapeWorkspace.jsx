import { useEffect, useRef, useState } from "react";
import Viewer from "../../components/Viewer.jsx";
import BatchPicker from "../facial/BatchPicker.jsx";
import { computeMeanShapeWithOutliers, meanShapeDownloadUrl, meanShapeMeshUrl } from "../../api/cohort.js";
import { sanitizeSegment } from "../cohort/lib/naming.js";
import { heatmapMax } from "../../three/measurementsLayer.js";

// 5th and final top-level workspace (see components/shell/Shell.jsx's nav)
// - a freeform mean-shape tool: add any set of meshes assumed already
// NICP-fitted to the same template (not tied to a loaded cohort
// spreadsheet the way workspaces/cohort/tabs/MeanShapeTab.jsx is - a plain
// picked-paths list instead), then average them into a single mean shape.
// reuses facial/BatchPicker.jsx as-is for the picker (already fully
// generic - desktop-only, since the picked meshes are read straight off
// disk, same reasoning that component's own docstring already gives).
//
// a mesh whose topology/vertex count doesn't match the majority of the
// group is automatically excluded rather than aborting the whole
// computation, and reported back by filename+reason (see
// craniumpy_core.cohort.mean_shape_with_outliers) - the same "leave it out
// and report it" requirement facial/BatchFailuresSummary.jsx now also
// surfaces for the Facial Anthropometrics batch, just with a majority-vote
// reference here since (unlike that workspace) there's no pre-designated
// template to compare against.
export default function MeanShapeWorkspace({ onSnapshotChange, initialSnapshot }) {
  const viewerRef = useRef(null);
  const [meshPaths, setMeshPaths] = useState(initialSnapshot?.meshPaths ?? []);
  const [pickStatus, setPickStatus] = useState("");
  const [computing, setComputing] = useState(false);
  const [status, setStatus] = useState("");
  // {resultId, vertexCount, sourceCount, heatmap, excluded} | null -
  // deliberately kept in the snapshot (unlike Facial's own measurementValues)
  // since it's a real result the user computed, not something trivially
  // re-fetched - restored on mount below if the server cache still has it.
  const [result, setResult] = useState(initialSnapshot?.result ?? null);
  const [subscript, setSubscript] = useState("");

  useEffect(() => {
    onSnapshotChange?.({ meshPaths, result });
  }, [meshPaths, result, onSnapshotChange]);

  // mount only: restore a snapshotted mean shape into the viewer if the
  // server-side cache (api/routers/cohort.py's _mean_shape_cache, small and
  // FIFO-evicted) still has it - same "try to restore, fall back to a clean
  // slate on failure" pattern FacialWorkspace.jsx's own template-restore
  // effect uses.
  useEffect(() => {
    if (!result) return;
    (async () => {
      try {
        await viewerRef.current?.displayMesh(meanShapeMeshUrl(result.resultId), { selectionHasTexture: false });
        viewerRef.current.showSequentialHeatmap(result.heatmap);
        viewerRef.current.setMeshOpacity(1.0);
      } catch {
        setResult(null);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handlePathsPicked(paths, errorMsg) {
    if (errorMsg) {
      setPickStatus(errorMsg);
      return;
    }
    if (!paths || paths.length === 0) return;
    setMeshPaths((prev) => {
      const merged = [...prev];
      for (const p of paths) if (!merged.includes(p)) merged.push(p);
      return merged;
    });
    setPickStatus("");
  }

  function handleRemovePath(path) {
    setMeshPaths((prev) => prev.filter((p) => p !== path));
  }

  async function handleCompute() {
    setComputing(true);
    setStatus("computing mean shape...");
    setResult(null);
    try {
      const response = await computeMeanShapeWithOutliers(meshPaths);
      await viewerRef.current.displayMesh(meanShapeMeshUrl(response.resultId), { selectionHasTexture: false });
      viewerRef.current.showSequentialHeatmap(response.heatmap);
      viewerRef.current.setMeshOpacity(1.0);
      setResult(response);
      setStatus("");
    } catch (err) {
      setStatus(`failed: ${err.message}`);
    } finally {
      setComputing(false);
    }
  }

  function handleDownload() {
    if (!result) return;
    const base = `mean_shape_${result.sourceCount}_meshes`;
    const filename = subscript.trim() ? `${base}_${sanitizeSegment(subscript)}.ply` : `${base}.ply`;
    window.location.href = meanShapeDownloadUrl(result.resultId, filename);
  }

  function basename(path) {
    return path.split(/[\\/]/).pop();
  }

  return (
    <div className="meanshape-ws">
      <div className="meanshape-ws-viewer">
        <Viewer ref={viewerRef} wireframe={false} textureEnabled={false} landmarks={{}} landmarkColors={{}} />
        {!result && <p className="hint overlay">Pick meshes and compute a mean shape to see it here.</p>}
        {result && (
          <div className="heatmap-scalar-bar">
            <span>+{heatmapMax(result.heatmap).toFixed(1)} mm spread</span>
            <div className="scalar-bar-gradient scalar-bar-gradient-sequential" />
            <span>0 mm</span>
          </div>
        )}
      </div>
      <div className="meanshape-ws-sidebar">
        <p className="hint">
          Add meshes already NICP-fitted to the same template, then compute their averaged mean shape - a vertex-by-
          vertex average, meaningful because same-template meshes share exact point correspondence. A mesh with a
          different topology or vertex count is automatically excluded and reported, never silently dropped.
        </p>
        <BatchPicker onPathsPicked={handlePathsPicked} status={pickStatus} />
        {meshPaths.length > 0 && (
          <>
            <p className="hint">
              {meshPaths.length} mesh{meshPaths.length === 1 ? "" : "es"} picked:
            </p>
            <ul className="meanshape-ws-picked-list">
              {meshPaths.map((p) => (
                <li key={p}>
                  <span>{basename(p)}</span>
                  <button type="button" className="button-subtle" onClick={() => handleRemovePath(p)}>
                    remove
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="button-subtle" onClick={() => setMeshPaths([])}>
              clear all
            </button>
          </>
        )}
        <button type="button" onClick={handleCompute} disabled={computing || meshPaths.length === 0}>
          compute mean shape
        </button>
        {status && <p className="status-line">{status}</p>}

        {result && (
          <>
            <p className="hint">
              {result.sourceCount} mesh{result.sourceCount === 1 ? "" : "es"} averaged, {result.vertexCount} vertices.
            </p>
            {result.excluded.length > 0 && (
              <div className="meanshape-ws-excluded">
                <p className="hint">
                  {result.excluded.length} excluded:
                </p>
                <ul>
                  {result.excluded.map((e) => (
                    <li key={e.path}>
                      <strong>{basename(e.path)}</strong>: {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <label htmlFor="meanshape-subscript">filename subscript (optional)</label>
            <input
              id="meanshape-subscript"
              type="text"
              value={subscript}
              onChange={(e) => setSubscript(e.target.value)}
              placeholder="e.g. cohort-a"
            />
            <button type="button" className="button-subtle" onClick={handleDownload}>
              download mesh (.ply)
            </button>
          </>
        )}
      </div>
    </div>
  );
}
