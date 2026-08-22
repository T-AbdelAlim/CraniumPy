import { isDesktopApp, pickFileNative, pickFolderNative } from "../../lib/desktop.js";
import { listMeshesInFolder } from "../../api/facial.js";

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

  if (!isDesktopApp()) {
    return <p className="hint">Batch extraction needs the desktop app (it reads mesh files straight from disk).</p>;
  }

  return (
    <div className="facial-batch-picker">
      <button type="button" onClick={handlePickFiles}>
        choose mesh file(s)...
      </button>
      <button type="button" className="button-subtle" onClick={handlePickFolder}>
        choose a folder of meshes...
      </button>
      {status && <p className="status-line">{status}</p>}
    </div>
  );
}
