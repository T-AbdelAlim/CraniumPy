import { useState } from "react";
import { isDesktopApp, pickFileNative, pickFolderNative, waitForNativeDropPaths } from "../../lib/desktop.js";
import { listMeshesInFolder } from "../../api/facial.js";
import { MESH_EXTENSIONS, extOf } from "../../lib/meshFiles.js";

// desktop-only, deliberately: the batch review step reloads each mesh
// fresh from its own real filesystem path on demand (see
// api/routers/facial.py's own module docstring - never holding more than
// one full mesh in memory at a time is the whole point of the "sensible
// loading/unloading" efficiency requirement), which only works with real
// paths. a browser upload has no such path (same limitation every other
// desktop-vs-browser split in this app already has - see
// workspaces/data/UploadPanel.jsx), and caching uploaded bytes server-side
// for the whole batch's lifetime would undermine that same efficiency goal.
export default function BatchPicker({ onPathsPicked, status }) {
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  async function handlePickFiles() {
    const paths = await pickFileNative(true, (msg) => onPathsPicked(null, `Couldn't open the file picker: ${msg}`));
    if (paths && paths.length > 0) onPathsPicked(paths, null);
  }

  async function handlePickFolder() {
    const folder = await pickFolderNative((msg) => onPathsPicked(null, `Couldn't open the folder picker: ${msg}`));
    if (!folder) return;
    try {
      const paths = await listMeshesInFolder(folder);
      if (paths.length === 0) {
        onPathsPicked(null, `No .ply/.obj/.stl files found in ${folder}`);
        return;
      }
      onPathsPicked(paths, null);
    } catch (err) {
      onPathsPicked(null, `Couldn't list meshes: ${err.message}`);
    }
  }

  // drag-and-drop straight onto the picker, one file at a time or several
  // at once (a plain multi-file OS drag drops them all in one event) - same
  // waitForNativeDropPaths resolution workspaces/meanshape/MeanShapeWorkspace.jsx's
  // own drop handling already uses. desktop-only, same reasoning as the
  // buttons above: a browser drop never exposes a real path, so nothing
  // ever resolves.
  function handleDragEnter(event) {
    event.preventDefault();
    setIsDraggingOver(true);
  }

  function handleDragOver(event) {
    event.preventDefault();
  }

  function handleDragLeave(event) {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setIsDraggingOver(false);
  }

  async function handleDrop(event) {
    event.preventDefault();
    setIsDraggingOver(false);
    const files = Array.from(event.dataTransfer?.files || []);
    const meshNames = files.map((f) => f.name).filter((n) => MESH_EXTENSIONS.includes(extOf(n)));
    if (meshNames.length === 0) {
      onPathsPicked(null, "No .ply/.obj/.stl found in the files you dropped");
      return;
    }
    const nativePaths = await waitForNativeDropPaths();
    const resolved = meshNames.filter((n) => nativePaths?.[n]).map((n) => nativePaths[n]);
    if (resolved.length === 0) {
      onPathsPicked(null, "Couldn't resolve a real file path for the dropped file(s) - this needs the desktop app.");
      return;
    }
    onPathsPicked(resolved, null);
  }

  if (!isDesktopApp()) {
    return <p className="hint">Batch extraction needs the desktop app (it reads mesh files straight from disk).</p>;
  }

  return (
    <div
      className={isDraggingOver ? "facial-batch-picker viewer-drag-active" : "facial-batch-picker"}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <button type="button" onClick={handlePickFiles}>
        choose mesh file(s)...
      </button>
      <button type="button" className="button-subtle" onClick={handlePickFolder}>
        choose a folder of meshes...
      </button>
      {status && <p className="status-line">{status}</p>}
      {isDraggingOver && <p className="viewer-drop-hint">Drop to add mesh(es)</p>}
    </div>
  );
}
