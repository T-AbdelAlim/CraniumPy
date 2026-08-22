// fetch wrappers for the /api/facial/* endpoints - same shape/conventions
// as api/cohort.js/api/sessions.js, including converting the backend's
// snake_case JSON into the camelCase shape every other wrapper in this app
// already hands back (see api/sessions.js's uploadSession for the same
// pattern). the actual geometry (geodesic distance, enclosed area) is all
// server-side (craniumpy_core.facial_measurements) - this is just the
// request/response plumbing.
import { downloadPost } from "./cohort.js";

function toCamelResult(r) {
  return {
    filename: r.filename,
    status: r.status,
    error: r.error,
    landmarkPoints: r.landmark_points,
    values: r.values,
    valueErrors: r.value_errors,
  };
}

// shipped_name defaults server-side to "template_face" when both fields are
// omitted - pass path instead for a custom template mesh.
export async function loadFacialTemplate({ shippedName, path } = {}) {
  const response = await fetch("/api/facial/template/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shipped_name: shippedName ?? null, path: path ?? null }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { templateId: data.template_id, vertexCount: data.vertex_count, faceCount: data.face_count };
}

export function facialTemplateMeshUrl(templateId) {
  return `/api/facial/template/${templateId}/mesh`;
}

// snaps a raw raycast-hit point to its nearest vertex on the template -
// call once per ctrl-click; the returned vertexIndex is what makes
// landmark transfer across a whole batch a plain array lookup later (see
// craniumpy_core.facial_measurements' own module docstring).
export async function pickFacialPoint(templateId, point) {
  const response = await fetch(`/api/facial/template/${templateId}/pick`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ point }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { vertexIndex: data.vertex_index, point: data.point };
}

// points: {pointId: {x,y,z}}, measurements: [{id, name, abbreviation, type,
// pointIds, geodesic, color}] (camelCase frontend shape - converted to the
// API's point_ids here) - live values while still defining measurements,
// computed directly on the template mesh.
export async function previewFacialMeasurements(templateId, points, measurements) {
  const response = await fetch(`/api/facial/template/${templateId}/measurement/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_id: templateId, points, measurements: measurements.map(toApiMeasurement) }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { values: data.values, valueErrors: data.value_errors };
}

// a picked folder only ever comes back as a path (see
// frontend/src/lib/desktop.js's pickFolderNative) - this expands it into
// the flat list of mesh files inside, the batch's own mesh paths.
export async function listMeshesInFolder(folder) {
  const response = await fetch("/api/facial/list-meshes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return data.mesh_paths;
}

function toApiMeasurement(m) {
  return {
    id: m.id,
    name: m.name,
    abbreviation: m.abbreviation,
    type: m.type,
    point_ids: m.pointIds,
    geodesic: !!m.geodesic,
    color: m.color,
  };
}

// one synchronous request for the whole batch - see api/routers/facial.py's
// own module docstring for why this doesn't need job-queue/progress-polling
// machinery (per-mesh work is cheap, topology is cached/reused per
// template). never throws on one bad file - check each result's own
// status/error instead.
export async function startFacialBatch(templateId, meshPaths, points, measurements) {
  const response = await fetch("/api/facial/batch/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_id: templateId,
      mesh_paths: meshPaths,
      points,
      measurements: measurements.map(toApiMeasurement),
    }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { batchId: data.batch_id, results: data.results.map(toCamelResult) };
}

export function facialBatchMeshUrl(batchId, filename) {
  return `/api/facial/batch/${batchId}/mesh/${encodeURIComponent(filename)}`;
}

// corrects one landmark on one file in the batch - recomputes and returns
// only the measurements that actually reference that point (see the
// backend's own measurements_by_point dependency map), never the whole file.
export async function correctFacialLandmark(batchId, filename, pointId, point) {
  const response = await fetch(`/api/facial/batch/${batchId}/correct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_id: batchId, filename, point_id: pointId, point }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return { landmarkPoint: data.landmark_point, values: data.values, valueErrors: data.value_errors };
}

// the batch's own Excel export (identifiers/names/abbreviations/types/
// units/values plus a color-swatch legend, and a "failed" sheet if any
// file errored) - see api/routers/facial.py's export_batch. this exact
// file is also what the Cohort workspace later loads as an attached
// dataset (see api/cohort.js's own facial-measurements load calls).
export async function downloadFacialBatchExport(batchId) {
  await downloadPost(`/api/facial/batch/${batchId}/export`, {}, "facial_measurements.xlsx");
}
