"""longitudinal/follow-up comparison endpoints: a per-vertex diff/heatmap
between two already-correspondent meshes, the same measurement suite the
Patients workspace's Analysis tab shows (run directly on an arbitrary
already-registered mesh, no session /run needed), and a two-timepoint PDF
report.

deliberately doesn't touch api.sessions.Session's own pipeline at all -
every endpoint here just reads a live session's own in-memory mesh (via
_resolve_mesh_ref), or a shipped template, and computes something. point
correspondence itself is never established here: every mesh the Longitudinal
workspace works with already got NICP-fit to a shared template in the
Patients workspace (POST /{session_id}/run with a NicpConfig.template - see
api/routers/mesh.py's start_run) before it ever reaches this workspace, so
there's nothing left to fit here."""

from __future__ import annotations

import trimesh
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from craniumpy_core import cohort
from craniumpy_core.template_registry import load_shipped_template
from api.results_bundle import longitudinal_comparison_report_pdf
from api.routers._group_measurements import group_measurements_response
from api.schemas import (
    CohortMeanShapeMeasurementsResponse,
    LongitudinalDiffRequest,
    LongitudinalDiffResponse,
    LongitudinalMeasureRequest,
    LongitudinalMeshRef,
    LongitudinalReportRequest,
)
from api.sessions import store

router = APIRouter(prefix="/api/longitudinal", tags=["longitudinal"])


def _resolve_mesh_ref(ref: LongitudinalMeshRef) -> trimesh.Trimesh:
    """the one shared lookup every endpoint below uses - a live session's
    own pipeline stage, or a shipped template (for the "distance heatmap"
    overlay's custom-reference mode - see CompareTab.jsx). 404s when the
    thing named doesn't exist at all, 409s when it exists but isn't
    ready/applicable yet - same status-code convention api/routers/mesh.py's
    own stage lookups (export_mesh) already use."""
    if ref.template is not None:
        try:
            return load_shipped_template(ref.template)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if ref.session_id is None:
        raise HTTPException(status_code=400, detail="mesh ref needs either session_id or template")

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


@router.post("/measure", response_model=CohortMeanShapeMeasurementsResponse)
def measure_mesh(request: LongitudinalMeasureRequest) -> CohortMeanShapeMeasurementsResponse:
    """the "already registered" fast path's numbers - no landmark picking,
    no session /run, works on ANY mesh already sitting in this app's
    canonical registered frame (see craniumpy_core.cohort.measure_mean_shape)."""
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
