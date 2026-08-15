// centralizes session-related fetch calls so components extend this module
// instead of scattering fetch() through them.

export async function uploadSession(files) {
  const formData = new FormData();
  for (const f of files) formData.append("files", f);
  const response = await fetch("/api/sessions", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { sessionId: data.session_id, vertexCount: data.vertex_count, faceCount: data.face_count };
}

// desktop: opens straight from real local paths (picked via lib/desktop.js's
// pickFileNative) instead of round-tripping bytes through a browser upload -
// remembers the containing folder on the session, so /save can write
// results back there without asking where (see api/routers/mesh.py's
// open_mesh_from_paths).
export async function openFromPaths(paths) {
  const response = await fetch("/api/sessions/from-paths", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { sessionId: data.session_id, vertexCount: data.vertex_count, faceCount: data.face_count };
}

export function meshUrl(sessionId, stage = "original") {
  return `/api/sessions/${sessionId}/mesh/${stage}`;
}

export async function fetchShippedTemplates() {
  const response = await fetch("/api/templates");
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // [{name, description}]
}

export function templateMeshUrl(name) {
  return `/api/templates/${name}/mesh`;
}

export function customTemplateMeshUrl(path) {
  return `/api/templates/custom/mesh?path=${encodeURIComponent(path)}`;
}

// browser-mode custom template - no real filesystem path to hand the
// server, so the file's bytes go up instead and come back as a GLB blob
// URL the viewer can load directly (see PreprocessingPanel's file input).
export async function uploadCustomTemplate(file) {
  const formData = new FormData();
  formData.append("files", file);
  const response = await fetch("/api/templates/custom/upload", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

// landmarks here is the fixed-order array the API expects ([sellion,
// left_tragus, right_tragus] as {x,y,z} objects), not the name-keyed dict
// components work with - callers convert via activeLandmarkNames().map(...).
export async function startAlign(sessionId, { target, landmarks, altFrontalLandmark }) {
  const body = { target, landmarks };
  if (altFrontalLandmark) body.alt_frontal_landmark = altFrontalLandmark;
  const response = await fetch(`/api/sessions/${sessionId}/align`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
}

export async function getRegisteredTransform(sessionId) {
  const response = await fetch(`/api/sessions/${sessionId}/registered-transform`);
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {rotation: 3x3 row-major, translation: [x,y,z]}
}

// register + repair + clip + boundary cleanup - the first of run-pipeline's
// two chained calls (see startRun below).
export async function startClip(sessionId, { target, landmarks, altFrontalLandmark, comTranslation }) {
  const body = { target, landmarks, com_translation: comTranslation, repair: true };
  if (altFrontalLandmark) body.alt_frontal_landmark = altFrontalLandmark;
  const response = await fetch(`/api/sessions/${sessionId}/clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
}

// resample (or nicp-fit, see nicp below) + measure, on whatever /clip
// already produced. nicp, when given, replaces the plain resample
// entirely - see api/schemas.py's NicpConfig for what each field means.
export async function startRun(sessionId, { nVertices, nicp }) {
  const body = { n_vertices: nVertices };
  if (nicp) {
    body.nicp = {
      template: nicp.template,
      custom_template_path: nicp.customTemplatePath,
      alpha_start: nicp.alphaStart,
      alpha_end: nicp.alphaEnd,
      alpha_steps: nicp.alphaSteps,
      gamma: nicp.gamma,
      dist_threshold: nicp.distThreshold,
      inner_iters: nicp.innerIters,
    };
  }
  const response = await fetch(`/api/sessions/${sessionId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
}

// desktop: writes just the two mesh files (_rg.ply / _rg_{C|F}.ply) next
// to the original mesh file, or into destDir if given (the "change save
// folder..." override - see api/schemas.py's SaveRequest). thrown errors
// carry a .status so a caller can tell "no real source path, fall back to
// meshesBundleUrl" (400) apart from a real failure worth surfacing, same
// as legacy's save-results button did.
export async function saveMeshes(sessionId, destDir) {
  const response = await fetch(`/api/sessions/${sessionId}/save/meshes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dest_dir: destDir || null }),
  });
  if (!response.ok) {
    const error = new Error(await response.text());
    error.status = response.status;
    throw error;
  }
  return response.json(); // {saved_to}
}

// browser: zip-download url for just the two mesh files.
export function meshesBundleUrl(sessionId) {
  return `/api/sessions/${sessionId}/bundle/meshes`;
}

// craniometrics/asymmetry for the Analysis workspace - see
// api/schemas.py's ResultsResponse.
export async function getResults(sessionId) {
  const response = await fetch(`/api/sessions/${sessionId}/results`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

// desktop: writes the report/figures into the mesh folder's analysis/
// subfolder, creating the mesh folder (and its mesh files) first if it
// doesn't exist yet - see api/results_bundle.write_analysis_to_folder.
// destDir/error-shape same as saveMeshes above.
export async function saveAnalysis(sessionId, destDir) {
  const response = await fetch(`/api/sessions/${sessionId}/save/analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dest_dir: destDir || null }),
  });
  if (!response.ok) {
    const error = new Error(await response.text());
    error.status = response.status;
    throw error;
  }
  return response.json(); // {saved_to}
}

// browser: zip-download url for the meshes plus a nested analysis/.
export function analysisBundleUrl(sessionId) {
  return `/api/sessions/${sessionId}/bundle/analysis`;
}

// polls /status until the job is done or errored, returning the final
// payload - written generically since /align, /clip, and /run all need the
// identical loop. onProgress(stage, detail, progress) fires on every tick,
// including the terminal one ("done" with an empty detail, or "error" with
// the error message as detail), so a caller can drive a live status line or
// progress bar from it. the 3rd arg is the raw {stage, detail, current,
// total} progress object (or null) - only "nicp" ticks populate
// current/total, for callers driving a numeric stiffness-step progress bar.
export async function pollStatus(sessionId, onProgress) {
  while (true) {
    const response = await fetch(`/api/sessions/${sessionId}/status`);
    const data = await response.json();
    if (data.status === "done") {
      onProgress?.("done", "", data.progress ?? null);
      return data;
    }
    if (data.status === "error") {
      onProgress?.("error", data.error, data.progress ?? null);
      return data;
    }
    if (data.progress) onProgress?.(data.progress.stage, data.progress.detail, data.progress);
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

// polled while a "fit template" job is running, for a live view of the
// template converging onto the mesh - 409s until the fit's done its first
// stiffness step.
export function nicpPreviewMeshUrl(sessionId) {
  return `/api/sessions/${sessionId}/mesh/nicp-preview`;
}
