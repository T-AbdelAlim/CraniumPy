import { useRef, useState } from "react";
import { uploadSession } from "../../api/sessions.js";
import { hasMeshFile, hasTextureFile, primaryMeshFile } from "../../lib/meshFiles.js";

export default function UploadPanel({ onUploaded }) {
  const fileInputRef = useRef(null);
  const [meshPath, setMeshPath] = useState("");
  const [status, setStatus] = useState("");

  function handleChooseFile() {
    fileInputRef.current.click();
  }

  async function handleFilesSelected(event) {
    const files = Array.from(event.target.files);
    event.target.value = ""; // lets the same file(s) be picked again later
    if (files.length === 0) return;

    const names = files.map((f) => f.name);
    if (!hasMeshFile(names)) {
      setStatus("No .ply/.obj/.stl found in the files you picked");
      return;
    }

    const meshLabel = primaryMeshFile(names) ?? "";
    setMeshPath(meshLabel);
    setStatus("Uploading...");
    try {
      const { sessionId, vertexCount, faceCount } = await uploadSession(files);
      setStatus(`${vertexCount} vertices, ${faceCount} faces`);
      onUploaded({ sessionId, meshLabel, selectionHasTexture: hasTextureFile(names) });
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
        file picker.
      </p>
      <p className="hint">{meshPath}</p>
      <p className="hint">{status}</p>
    </section>
  );
}
