// fetch wrappers for the /api/cohort/* endpoints - same shape/conventions as
// api/sessions.js. descriptive stats/plotting stay entirely client-side (see
// workspaces/cohort/lib/stats.js) - these are only the calls that genuinely
// need the backend: reading a cohort spreadsheet off disk/upload, running a
// real inferential statistical test (scipy.stats), and computing a mean 3D
// shape from same-template NICP-fitted meshes (trimesh, real mesh I/O).

// desktop: load straight from a real local path (native file dialog result).
export async function loadCohortFile(path) {
  const response = await fetch("/api/cohort/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {columns, rows}
}

// the shipped ~150-row synthetic cohort (see scripts/generate_demo_cohort.py)
// - same shape as loadCohortFile/uploadCohortFile, works identically in
// desktop and browser mode since it's read server-side either way.
export async function loadDemoCohort() {
  const response = await fetch("/api/cohort/demo");
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {columns, rows}
}

// browser: upload the file's bytes instead - no persistent local path to
// point the server at from inside a browser tab.
export async function uploadCohortFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/api/cohort/upload", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {columns, rows}
}

// the Per-patient sidebar's "load from cohort" dropdown - every unique
// patient already in this cohort (see api/results_bundle.py's
// list_cohort_patients), for freezing the form onto one instead of
// retyping their details for a follow-up image. path is the same
// cohort.xlsx path "add to existing cohort file..." already resolved.
export async function listCohortPatients(path) {
  const response = await fetch("/api/cohort/patients", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return data.patients; // [{patient_id, date_of_birth, date_of_intervention, sex, diagnosis, treatment}]
}

// values: {group label: numeric values[]}. returns both a parametric and a
// rank-based/nonparametric result together (see api/routers/cohort.py's
// _run_stats_test for which pair runs, 2 groups vs 3+) - which one to trust
// depends on sample size/distribution shape, not something this call can
// judge on the caller's behalf.
export async function runStatsTest(values) {
  const response = await fetch("/api/cohort/stats-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

// meshPaths must all be NICP-fitted to the identical template (see
// craniumpy_core.cohort.mean_shape) - a mismatch comes back as a real error
// message, not a silently-wrong average.
export async function computeMeanShape(meshPaths) {
  const response = await fetch("/api/cohort/mean-shape", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mesh_paths: meshPaths }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {result_id, vertex_count, source_count, heatmap}
}

export function meanShapeMeshUrl(resultId) {
  return `/api/cohort/mean-shape/${resultId}/mesh`;
}

// signed displacement (mm) of an already-computed mean shape from a
// shipped reference template (see craniumpy_core.cohort.reference_diff) -
// template must match the mean shape's own topology (same nicp_template
// name, in practice) or this comes back as a 400 with a clear message.
export async function computeReferenceDiff(resultId, template) {
  const response = await fetch(
    `/api/cohort/mean-shape/${resultId}/reference-diff?template=${encodeURIComponent(template)}`,
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {heatmap}
}

// the same measurement suite the Patients workspace's Analysis tab shows
// (craniometrics/asymmetry/metopic/frontal_bossing), run directly on an
// already-computed mean shape - see craniumpy_core.cohort.measure_mean_shape.
// target must be "cranium" or "face", matching the group's own rows.
export async function computeMeanShapeMeasurements(resultId, target) {
  const response = await fetch(
    `/api/cohort/mean-shape/${resultId}/measurements?target=${encodeURIComponent(target)}`,
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {craniometrics, asymmetry, metopic, frontal_bossing}
}

// the mean shape as a downloadable .ply, named `filename` (see
// workspaces/cohort/lib/naming.js for how that's built from the active
// filters) - a plain GET url rather than a fetch wrapper, meant for
// window.location.href / an <a download> style trigger, same as the
// Patients workspace's own bundle-download urls (see api/sessions.js's
// meshesBundleUrl/analysisBundleUrl).
export function meanShapeDownloadUrl(resultId, filename) {
  return `/api/cohort/mean-shape/${resultId}/download?filename=${encodeURIComponent(filename)}`;
}

// mean +/- SD of the group's sagittal midline forehead-to-vertex depth
// profile - see craniumpy_core.cohort.sagittal_midline_band. computed from
// mesh_paths directly (not a cached mean-shape result_id), since it needs
// every individual mesh, not just their average.
export async function computeSagittalBand(meshPaths, target) {
  const response = await fetch("/api/cohort/sagittal-band", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mesh_paths: meshPaths, target }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {y, mean_z, sd_z, source_count}
}

// shared by any POST endpoint that returns a downloadable file rather than
// JSON (the mean-shape PDF report, the cohort xlsx export, the Facial
// Anthropometrics workspace's own batch export - see api/facial.js) -
// fetches the blob, then triggers a save through a throwaway <a download>
// click, the standard way to save a POST response client-side (a plain GET
// url like meanShapeDownloadUrl's can just be handed to
// window.location.href instead, but a POST body has nowhere to go in a
// URL). fallbackFilename is only used if the response didn't carry its own
// Content-Disposition name (every endpoint that actually uses this always
// does, in practice). exported (not cohort-specific despite living here)
// rather than duplicated - this is the one place that logic lives.
export async function downloadPost(url, body, fallbackFilename) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : fallbackFilename;
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(blobUrl);
}

// downloads the mean-shape PDF report - see api/results_bundle.py's
// mean_shape_report_pdf. groupLabel is shown on the report's own title
// page and used to name the file (see lib/naming.js for the same
// filename-building the mesh download uses); includeSpreadBands toggles
// every spread visualization the report can show - the sagittal/frontal-
// bossing band always, plus the HC-ring band (cranium) or metopic band
// (face), whichever applies (see schemas.CohortReportRequest).
export async function downloadMeanShapeReport(meshPaths, target, groupLabel, includeSpreadBands) {
  await downloadPost(
    "/api/cohort/report",
    { mesh_paths: meshPaths, target, group_label: groupLabel, include_spread_bands: includeSpreadBands },
    "mean_shape_report.pdf",
  );
}

// +/-1 SD ribbon (real 3D points) around the group's HC ring - see
// craniumpy_core.cohort.hc_ring_band. same request shape as
// computeSagittalBand.
export async function computeHcRingBand(meshPaths, target) {
  const response = await fetch("/api/cohort/hc-ring-band", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mesh_paths: meshPaths, target }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {mean, inner, outer, closed, source_count}
}

// +/-1 SD ribbon (real 3D points) around the group's metopic forehead
// contour - see craniumpy_core.cohort.metopic_band. same request shape as
// computeSagittalBand.
export async function computeMetopicBand(meshPaths, target) {
  const response = await fetch("/api/cohort/metopic-band", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mesh_paths: meshPaths, target }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {mean, inner, outer, closed, source_count}
}

// a formatted Excel workbook - sheets is [{title, columns, rows}], see
// api/routers/cohort.py's _build_export_xlsx for the actual formatting
// (colored header, banded rows, frozen header, auto-numeric columns).
export async function downloadCohortExportXlsx(sheets, filename) {
  await downloadPost("/api/cohort/export-xlsx", { sheets, filename }, "cohort_export.xlsx");
}

// attaches a Facial Anthropometrics batch export (frontend/src/api/facial.js's
// downloadFacialBatchExport, api/routers/facial.py's export_batch) to this
// cohort as a lazily-joined dataset, matched by mesh filename - never merged
// into the cohort file itself (see api/routers/cohort.py's
// load_facial_measurements). unmatched/ambiguous filenames come back
// alongside the matched rows so the caller can warn before committing the
// merge, rather than a separate "check first" round trip.
export async function loadFacialMeasurements(cohortPath, measurementFilePath) {
  const response = await fetch("/api/cohort/facial-measurements/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cohort_path: cohortPath, measurement_file_path: measurementFilePath }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return {
    columns: data.columns,
    rowsByCohortId: data.rows_by_cohort_id,
    legend: data.legend,
    unmatched: data.unmatched,
    ambiguous: data.ambiguous,
  };
}
