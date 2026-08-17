import { useRef, useState } from "react";
import { openFromPaths, uploadSession } from "../../api/sessions.js";
import { hasMeshFile, hasTextureFile, primaryMeshFile } from "../../lib/meshFiles.js";
import { isDesktopApp, pickFileNative } from "../../lib/desktop.js";

export default function UploadPanel({ onUploaded }) {
  const fileInputRef = useRef(null);
  const [meshPath, setMeshPath] = useState("");
  const [status, setStatus] = useState("");

  // desktop: a native path-based open (so the session gets a real
  // source_dir and /save* can auto-save next to it, no folder prompt -
  // see api/routers/mesh.py's open_mesh_from_paths). browser: the plain
  // <input type=file> below, since a browser sandbox never hands back a
  // real filesystem path regardless of which machine the tab happens to
  // be pointed at.
  async function handleChooseFile() {
    if (!isDesktopApp()) {
      fileInputRef.current.click();
      return;
    }
    const paths = await pickFileNative(true, (msg) => setStatus(`Couldn't open the file picker: ${msg}`));
    if (!paths || paths.length === 0) return;
    const names = paths.map((p) => p.split(/[\\/]/).pop());
    // the primary mesh's own full native path - lets the metadata form
    // pre-fill file_path (see App.jsx's handleUploaded) - only meaningful
    // here since paths came from a native dialog; browser uploads never
    // have one (see handleFilesSelected below).
    const primaryName = primaryMeshFile(names);
    const filePath = primaryName ? paths[names.indexOf(primaryName)] : "";
    await openMesh(names, () => openFromPaths(paths), filePath);
  }

  async function handleFilesSelected(event) {
    const files = Array.from(event.target.files);
    event.target.value = ""; // lets the same file(s) be picked again later
    if (files.length === 0) return;
    await openMesh(
      files.map((f) => f.name),
      () => uploadSession(files),
      "", // browser File objects never expose a real filesystem path
    );
  }

  // shared tail of both open paths above - names is just the file
  // basenames (from a File[] or from native paths), doOpen is whichever
  // API call actually creates the session, filePath is the primary mesh's
  // full native path when known (desktop only, "" otherwise).
  async function openMesh(names, doOpen, filePath) {
    if (!hasMeshFile(names)) {
      setStatus("No .ply/.obj/.stl found in the files you picked");
      return;
    }

    const meshLabel = primaryMeshFile(names) ?? "";
    setMeshPath(meshLabel);
    setStatus("Uploading...");
    try {
      const { sessionId, vertexCount, faceCount } = await doOpen();
      setStatus(`${vertexCount} vertices, ${faceCount} faces`);
      onUploaded({ sessionId, meshLabel, filePath, selectionHasTexture: hasTextureFile(names) });
    } catch (err) {
      setStatus(`Upload failed: ${err.message}`);
    }
  }

  return (
    <section>
      <button type="button" onClick={handleChooseFile}>
        choose file(s)...
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".ply,.obj,.stl,.mtl,.jpg,.jpeg,.png"
        multiple
        className="hidden"
        onChange={handleFilesSelected}
      />
      <p className="hint">
        For a textured .obj, multi-select (ctrl/cmd-click) the .obj, its .mtl, and the texture image together in the
        file picker. You can also drag a mesh file straight onto the viewer instead of browsing for it.
      </p>
      <p className="hint">{meshPath}</p>
      <p className="hint">{status}</p>
    </section>
  );
}
