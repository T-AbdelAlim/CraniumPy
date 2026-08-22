// fetch wrappers for the /api/longitudinal/* endpoints - same shape/
// conventions as api/sessions.js and api/cohort.js. everything else the
// Longitudinal workspace needs (per-timepoint upload/align/clip/run, and
// NICP-fitting a mesh to a shared template) is already covered by
// api/sessions.js - every mesh this workspace works with already got
// NICP-fit to a shared template in the Patients workspace before it ever
// reaches here, so there's no fitting left to do in this module. these are
// only the genuinely new operations: the measurement suite run on an
// arbitrary already-registered mesh, a per-vertex diff between two
// same-topology meshes, and the two-timepoint PDF report.

// a mesh ref is either {sessionId, stage} (a live per-timepoint session's
// own pipeline stage - "original"/"clipped"/"result"/"nicp_result") or
// {template} (a shipped template, for the "distance heatmap" overlay's
// custom-reference mode).
function meshRefBody({ sessionId, stage, template }) {
  if (template) return { template };
  return { session_id: sessionId, stage: stage || "nicp_result" };
}

// the same measurement suite the Patients workspace's Analysis tab shows
// (craniometrics/asymmetry/metopic/frontal_bossing - see
// api/schemas.py's CohortMeanShapeMeasurementsResponse), run directly on an
// already-registered mesh ref with no landmark picking or session /run
// needed. this is what backs the "load pre-registered (NICP) file" fast
// path's numbers.
export async function measureMesh(ref, target) {
  const response = await fetch("/api/longitudinal/measure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: meshRefBody(ref), target }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {craniometrics, asymmetry, metopic, frontal_bossing}
}

// signed per-vertex displacement (mm) of meshRefB from meshRefA, along
// meshRefA's own normals - both refs must resolve to the same template
// topology (same vertex count/face connectivity), or this comes back as a
// real error message rather than a silently meaningless comparison. see
// craniumpy_core.cohort.reference_diff.
export async function computeLongitudinalDiff(meshRefA, meshRefB) {
  const response = await fetch("/api/longitudinal/diff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mesh_a: meshRefBody(meshRefA), mesh_b: meshRefBody(meshRefB) }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json(); // {heatmap, vertex_count}
}

// the two-timepoint comparison PDF (see
// api/results_bundle.longitudinal_comparison_report_pdf) - returns a blob
// URL the caller can open/download, same pattern the cohort report button
// uses for its own PDF download.
export async function downloadLongitudinalReport(meshRefA, meshRefB, target, labelA, labelB, includeDiff) {
  const response = await fetch("/api/longitudinal/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mesh_a: meshRefBody(meshRefA),
      mesh_b: meshRefBody(meshRefB),
      target,
      label_a: labelA,
      label_b: labelB,
      include_diff: includeDiff,
    }),
  });
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
