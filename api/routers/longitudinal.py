"""longitudinal/follow-up comparison endpoints: direct patient-to-patient
NICP fitting, a per-vertex diff/heatmap between two already-correspondent
meshes, and a two-timepoint PDF report.

deliberately doesn't touch api.sessions.Session at all - every endpoint here
just reads a live session's own in-memory mesh (via _resolve_mesh_ref) or a
previously-completed direct-fit result, computes something, and hands back a
plain response. the two ordinary per-timepoint pipelines (upload -> align ->
clip -> run, one session per compared image) are driven entirely through the
existing /api/sessions/* endpoints (api/routers/mesh.py) - nothing here
duplicates that.

"both timepoints fit to the same shipped/custom template" needs no code in
this file at all: that's just each session's own existing POST
/{session_id}/run with the same NicpConfig.template, which already produces
same-topology nicp_result_mesh fields on both sessions - see
api/routers/mesh.py's start_run. this file only adds what that flow can't
already do: fitting one patient's own mesh directly onto another's
(register_template with a live patient mesh as the "template" instead of a
shipped one), and the diff/report operations that make sense once two meshes
share a topology, however they got there.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import trimesh
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from craniumpy_core import cohort, pipeline
from craniumpy_core.io import mesh_to_glb
from api.results_bundle import longitudinal_comparison_report_pdf
from api.routers._group_measurements import group_measurements_response
from api.schemas import (
    CohortMeanShapeMeasurementsResponse,
    LongitudinalDiffRequest,
    LongitudinalDiffResponse,
    LongitudinalFitStatusResponse,
    LongitudinalMeasureRequest,
    LongitudinalMeshRef,
    LongitudinalNicpFitRequest,
    LongitudinalNicpFitResponse,
    LongitudinalReportRequest,
    ProgressInfo,
)
from api.sessions import store

router = APIRouter(prefix="/api/longitudinal", tags=["longitudinal"])


@dataclass
class _FitJob:
    id: str
    status: Literal["running", "done", "error"] = "running"
    error: str | None = None
    progress: dict = field(default_factory=lambda: {"stage": "starting", "detail": "", "current": None, "total": None})
    result_mesh: trimesh.Trimesh | None = None


# separate from api.sessions' own executor/store - a direct fit isn't "the
# pipeline for one session", it consumes two sessions' meshes and produces a
# third, independent artifact that outlives either session's own pipeline
# state. capped/FIFO-evicted, same "no real persistence needed" reasoning as
# api/routers/cohort.py's _mean_shape_cache.
_fit_executor = ThreadPoolExecutor(max_workers=1)
_fit_jobs: dict[str, _FitJob] = {}
_FIT_JOBS_MAX = 20
_fit_jobs_lock = threading.Lock()


def _cache_fit_job(job: _FitJob) -> None:
    with _fit_jobs_lock:
        _fit_jobs[job.id] = job
        while len(_fit_jobs) > _FIT_JOBS_MAX:
            _fit_jobs.pop(next(iter(_fit_jobs)))


def _resolve_mesh_ref(ref: LongitudinalMeshRef) -> trimesh.Trimesh:
    """the one shared lookup every endpoint below uses - a live session's
    own pipeline stage, or a previously-completed direct-fit result. 404s
    when the thing named doesn't exist at all, 409s when it exists but
    isn't ready/applicable yet - same status-code convention
    api/routers/mesh.py's own stage lookups (export_mesh) already use."""
    if ref.fit_id is not None:
        job = _fit_jobs.get(ref.fit_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no fit {ref.fit_id!r} (or it's since been evicted)")
        if job.status != "done":
            raise HTTPException(status_code=409, detail=f"fit {ref.fit_id!r} is {job.status}, not done yet")
        return job.result_mesh

    if ref.session_id is None:
        raise HTTPException(status_code=400, detail="mesh ref needs either session_id or fit_id")

    try:
        session = store.get(ref.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session {ref.session_id!r}")

    mesh = {
        "original": session.mesh,
        "clipped": session.clipped_mesh,
        "result": session.result_mesh,
        "nicp_result": session.nicp_result_mesh,
    }[ref.stage]
    if mesh is None:
        stage_hint = {"clipped": "/clip", "result": "/run", "nicp_result": "/run with nicp"}[ref.stage]
        raise HTTPException(
            status_code=409, detail=f"session {ref.session_id!r} has no {ref.stage!r} mesh yet -- run {stage_hint} first"
        )
    return mesh


@router.post("/nicp-fit", response_model=LongitudinalNicpFitResponse)
def start_nicp_fit(request: LongitudinalNicpFitRequest) -> LongitudinalNicpFitResponse:
    """direct patient-to-patient NICP: source_ref's mesh deforms to fit
    target_ref's mesh, ending up in source_ref's own topology - vertex-
    correspondent with source_ref, comparable to target_ref via /diff.
    runs as a background job (same reasoning as /run's own NICP path - a
    real fit takes real time) - poll GET .../{fit_id}/status."""
    source_mesh = _resolve_mesh_ref(request.source_ref)
    target_mesh = _resolve_mesh_ref(request.target_ref)

    job = _FitJob(id=str(uuid.uuid4()))
    _cache_fit_job(job)

    def _on_progress(step: int, total: int) -> None:
        job.progress = {"stage": "nicp", "detail": f"stiffness step {step}/{total}", "current": step, "total": total}

    def _run() -> None:
        try:
            job.result_mesh = pipeline.register_template(
                source_mesh,
                target_mesh,
                alphas=np.linspace(request.alpha_start, request.alpha_end, request.alpha_steps),
                gamma=request.gamma,
                dist_threshold=request.dist_threshold,
                inner_iters=request.inner_iters,
                on_progress=_on_progress,
            )
            job.status = "done"
            job.progress = {"stage": "done", "detail": "", "current": None, "total": None}
        except Exception as exc:  # noqa: BLE001 - want the client to see whatever went wrong
            job.error = str(exc)
            job.status = "error"

    _fit_executor.submit(_run)
    return LongitudinalNicpFitResponse(fit_id=job.id)


@router.get("/nicp-fit/{fit_id}/status", response_model=LongitudinalFitStatusResponse)
def get_nicp_fit_status(fit_id: str) -> LongitudinalFitStatusResponse:
    job = _fit_jobs.get(fit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no fit {fit_id!r} (or it's since been evicted)")
    progress = ProgressInfo(
        stage=job.progress["stage"], detail=job.progress["detail"],
        current=job.progress.get("current"), total=job.progress.get("total"),
    )
    return LongitudinalFitStatusResponse(status=job.status, error=job.error, progress=progress)


@router.get("/nicp-fit/{fit_id}/mesh")
def get_nicp_fit_mesh(fit_id: str):
    job = _fit_jobs.get(fit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no fit {fit_id!r} (or it's since been evicted)")
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"fit {fit_id!r} is {job.status}, not done yet")
    glb_bytes = mesh_to_glb(job.result_mesh)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@router.post("/measure", response_model=CohortMeanShapeMeasurementsResponse)
def measure_mesh(request: LongitudinalMeasureRequest) -> CohortMeanShapeMeasurementsResponse:
    """the "already registered" fast path's numbers, and also what the
    Correspondence tab uses to measure a fresh direct-fit result - no
    landmark picking, no session /run, works on ANY mesh already sitting
    in this app's canonical registered frame (see
    craniumpy_core.cohort.measure_mean_shape)."""
    mesh = _resolve_mesh_ref(request.ref)
    gm = cohort.measure_mean_shape(mesh, request.target)
    return group_measurements_response(mesh, gm)


@router.post("/diff", response_model=LongitudinalDiffResponse)
def compute_diff(request: LongitudinalDiffRequest) -> LongitudinalDiffResponse:
    mesh_a = _resolve_mesh_ref(request.mesh_a)
    mesh_b = _resolve_mesh_ref(request.mesh_b)
    try:
        heatmap = cohort.reference_diff(mesh_b, mesh_a)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LongitudinalDiffResponse(heatmap=heatmap.tolist(), vertex_count=len(mesh_b.vertices))


@router.post("/report")
def generate_report(request: LongitudinalReportRequest):
    mesh_a = _resolve_mesh_ref(request.mesh_a)
    mesh_b = _resolve_mesh_ref(request.mesh_b)

    measurements_a = cohort.measure_mean_shape(mesh_a, request.target)
    measurements_b = cohort.measure_mean_shape(mesh_b, request.target)

    diff_heatmap = None
    if request.include_diff:
        try:
            diff_heatmap = cohort.reference_diff(mesh_b, mesh_a)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    pdf_bytes = longitudinal_comparison_report_pdf(
        mesh_a, mesh_b, request.target, request.label_a, request.label_b,
        measurements_a, measurements_b, diff_heatmap=diff_heatmap,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="longitudinal_comparison_report.pdf"'},
    )
