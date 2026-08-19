// fetch wrappers for the /api/longitudinal/* endpoints - same shape/
// conventions as api/sessions.js and api/cohort.js. everything else the
// Longitudinal workspace needs (per-timepoint upload/align/clip/run) is
// already covered by api/sessions.js - these are only the genuinely new
// operations: direct patient-to-patient NICP fitting, a per-vertex diff
// between two same-topology meshes, and the two-timepoint PDF report.

// a mesh ref is either {sessionId, stage} (a live per-timepoint session's
// own pipeline stage - "clipped"/"result"/"nicp_result") or {fitId} (a
// previously-completed direct-fit result from startNicpFit below).
function meshRefBody({ sessionId, stage, fitId }) {
  if (fitId) return { fit_id: fitId };
  return { session_id: sessionId, stage: stage || "nicp_result" };
}

// kicks off a direct patient-to-patient NICP fit - sourceRef's mesh becomes
// the deforming template, targetRef's mesh is what it's fit onto, ending up
// in sourceRef's own topology (vertex-correspondent with it). returns a
// fitId to poll via pollNicpFitStatus, then fetch via nicpFitMeshUrl.
export async function startNicpFit(sourceRef, targetRef, options = {}) {
  const body = {
    source_ref: meshRefBody(sourceRef),
    target_ref: meshRefBody(targetRef),
    alpha_start: options.alphaStart ?? 200.0,
    alpha_end: options.alphaEnd ?? 1.0,
    alpha_steps: options.alphaSteps ?? 20,
    gamma: options.gamma ?? 1.0,
    dist_threshold: options.distThreshold ?? 10.0,
    inner_iters: options.innerIters ?? 3,
  };
  const response = await fetch("/api/longitudinal/nicp-fit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  return data.fit_id;
}

// polls a direct-fit job until it's done or errored - same shape as
// api/sessions.js's pollStatus, written separately since a fit job lives in
// its own store (api/routers/longitudinal.py's _fit_jobs), not a session.
export async function pollNicpFitStatus(fitId, onProgress) {
  while (true) {
    const response = await fetch(`/api/longitudinal/nicp-fit/${fitId}/status`);
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

export function nicpFitMeshUrl(fitId) {
  return `/api/longitudinal/nicp-fit/${fitId}/mesh`;
}

// the same measurement suite the Patients workspace's Analysis tab shows
// (craniometrics/asymmetry/metopic/frontal_bossing - see
// api/schemas.py's CohortMeanShapeMeasurementsResponse), run directly on an
// already-registered mesh ref with no landmark picking or session /run
// needed. this is what backs both the "already registered" fast path's
// numbers and a fresh direct-fit result's numbers.
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
