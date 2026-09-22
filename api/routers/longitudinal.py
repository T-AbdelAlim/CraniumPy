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

from pathlib import Path

import trimesh
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import Response

from craniumpy_core import cohort
from craniumpy_core.template_registry import load_shipped_template
from api.results_bundle import longitudinal_comparison_report_pdf, trends_chart_png
from api.routers._group_measurements import group_measurements_response
from api.routers.cohort import _build_export_xlsx, _sanitize_filename
from api.schemas import (
    CohortExportSheet,
    CohortMeanShapeMeasurementsResponse,
    LongitudinalDiffRequest,
    LongitudinalDiffResponse,
    LongitudinalMeasureRequest,
    LongitudinalMeshRef,
    LongitudinalReportRequest,
    SaveResultsResponse,
    TrendsExportRequest,
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


def _resolve_export_folder(dest_dir_str: str, folder_name: str, default: str) -> Path:
    """dest_dir/sanitize(folder_name)/, created if needed - shared by
    trends_export and save_video below, the two Longitudinal exports that
    write straight to a user-picked folder rather than triggering a
    browser download (see TrendsTab.jsx/MorphControl.jsx). unlike
    api/routers/mesh.py's own _resolve_dest_dir, there's no session to fall
    back to for a default location - a Trends chart or a morph video spans
    several sessions/timepoints, so the frontend always sends a real,
    user-picked dest_dir here (that picker is desktop-only - see
    lib/desktop.js's pickFolderNative - so a mistaken/missing dest_dir
    reaching here at all is itself a real error, not a fallback case)."""
    dest_dir = Path(dest_dir_str)
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"not a real folder: {dest_dir}")
    safe_folder = _sanitize_filename(folder_name, extension="", default=default)
    out_dir = dest_dir / safe_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


@router.post("/trends-export", response_model=SaveResultsResponse)
def trends_export(request: TrendsExportRequest) -> SaveResultsResponse:
    """the Trends tab's one "export results" button - writes both the
    300dpi figure (trends_chart_png) and an xlsx of the same values (the
    same CohortExportSheet-shaped table the tab used to build for its own
    now-removed xlsx button, run through cohort.py's own generic sheet
    writer rather than a second copy of that formatting) into
    dest_dir/folder_name/ - desktop only, no mesh/session lookup needed,
    unlike every other endpoint in this file, since the values are already
    computed. folder_name comes pre-built from the frontend (patient id +
    timepoint range - see TrendsTab.jsx)."""
    out_dir = _resolve_export_folder(request.dest_dir, request.folder_name, default="trend_export")

    png_bytes = trends_chart_png(request.x_labels, request.series)
    (out_dir / "measurements_over_time.png").write_bytes(png_bytes)

    columns = ["Timepoint"] + [f"{s.label} ({s.unit})" if s.unit else s.label for s in request.series]
    rows = [
        {
            "Timepoint": label,
            **{
                (f"{s.label} ({s.unit})" if s.unit else s.label): ("" if s.values[i] is None else f"{s.values[i]:.2f}")
                for s in request.series
            },
        }
        for i, label in enumerate(request.x_labels)
    ]
    xlsx_bytes = _build_export_xlsx([CohortExportSheet(title="measurements_over_time", columns=columns, rows=rows)])
    (out_dir / "measurements_over_time.xlsx").write_bytes(xlsx_bytes)

    return SaveResultsResponse(saved_to=str(out_dir))


@router.post("/save-video", response_model=SaveResultsResponse)
async def save_video(
    video: UploadFile, dest_dir: str = Form(...), folder_name: str = Form(...), extension: str = Form("webm")
) -> SaveResultsResponse:
    """3D Morphing's "export video" button, desktop variant - the recording
    itself only ever exists as an in-browser MediaRecorder Blob (see
    MorphControl.jsx's handleExportVideo), so unlike every mesh/figure this
    app saves, there's nothing server-side to (re)compute here at all: this
    just writes the bytes the frontend already produced into
    dest_dir/folder_name/, the same folder-naming convention trends_export
    above uses (patient id + timepoint range). extension matches whichever
    codec the browser's own MediaRecorder actually used (see
    extensionForMimeType in MorphControl.jsx) - MediaRecorder tries several
    mime types in turn, so this can't be hardcoded to one."""
    out_dir = _resolve_export_folder(dest_dir, folder_name, default="morph_export")
    safe_extension = "".join(c for c in extension if c.isalnum()) or "webm"
    video_bytes = await video.read()
    (out_dir / f"morph_animation.{safe_extension}").write_bytes(video_bytes)
    return SaveResultsResponse(saved_to=str(out_dir))
