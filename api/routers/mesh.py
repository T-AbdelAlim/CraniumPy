"""upload / templates / analyze / status / results / export / bundle endpoints.

just a thin wrapper around craniumpy_core.pipeline - no actual algorithm code
should live in here, just request/response stuff and the async job plumbing
(see api/sessions.py).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import trimesh
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from trimesh.resolvers import ZipResolver

from craniumpy_core import pipeline
from craniumpy_core.clipping import cranial_clip, facial_clip
from craniumpy_core.io import strip_uninteresting_vertex_colors
from craniumpy_core.registration.rigid import FACE_REFERENCE_TRIANGLE, REFERENCE_TRIANGLE
from craniumpy_core.template_registry import SHIPPED_TEMPLATES, load_shipped_template
from api.results_bundle import build_results_bundle, results_folder_name, write_results_to_folder
from api.schemas import (
    AnalyzeRequest,
    AsymmetryResponse,
    CraniometricsResponse,
    LandmarkPoint,
    OpenFromPathsRequest,
    ResultsResponse,
    SaveResultsResponse,
    StatusResponse,
    TemplateInfo,
    UploadResponse,
)
from api.sessions import Session, store

MESH_EXTENSIONS = {"ply", "obj", "stl"}

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
templates_router = APIRouter(prefix="/api/templates", tags=["templates"])


def _get_session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session {session_id!r}")


def _load_primary_and_resolver(files: list[UploadFile]) -> tuple[str, dict[str, bytes]]:
    """returns (primary_filename, {filename: bytes}) for a multi-file upload.
    needs exactly one .ply/.obj/.stl in there somewhere."""
    contents_by_name: dict[str, bytes] = {}
    for f in files:
        contents_by_name[f.filename or ""] = f.file.read()

    primary_candidates = [
        name for name in contents_by_name if Path(name).suffix.lstrip(".").lower() in MESH_EXTENSIONS
    ]
    if len(primary_candidates) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"expected exactly one .ply/.obj/.stl file among the upload, got {len(primary_candidates)}",
        )
    return primary_candidates[0], contents_by_name


def _load_primary_and_resolver_from_paths(paths: list[str]) -> tuple[str, dict[str, bytes]]:
    """same deal as _load_primary_and_resolver, but for real filesystem
    paths picked by the desktop app's native file dialog instead of an HTTP
    multipart upload - see open_mesh_from_paths."""
    contents_by_name: dict[str, bytes] = {}
    for raw_path in paths:
        p = Path(raw_path)
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"file not found: {raw_path}")
        contents_by_name[p.name] = p.read_bytes()

    primary_candidates = [
        name for name in contents_by_name if Path(name).suffix.lstrip(".").lower() in MESH_EXTENSIONS
    ]
    if len(primary_candidates) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"expected exactly one .ply/.obj/.stl file among the selection, got {len(primary_candidates)}",
        )
    return primary_candidates[0], contents_by_name


def _load_mesh_from_upload(primary_name: str, contents_by_name: dict[str, bytes]) -> trimesh.Trimesh:
    suffix = Path(primary_name).suffix.lstrip(".").lower()
    auxiliary = {name: data for name, data in contents_by_name.items() if name != primary_name}
    resolver = ZipResolver(archive=auxiliary) if auxiliary else None
    try:
        mesh = trimesh.load(
            io.BytesIO(contents_by_name[primary_name]),
            file_type=suffix,
            process=False,
            force="mesh",
            resolver=resolver,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not read mesh: {exc}") from exc
    if not isinstance(mesh, trimesh.Trimesh):
        raise HTTPException(status_code=400, detail="file did not contain a single triangle mesh")
    return strip_uninteresting_vertex_colors(mesh)


@templates_router.get("", response_model=list[TemplateInfo])
def list_templates() -> list[TemplateInfo]:
    return [TemplateInfo(name=name, description=desc) for name, desc in SHIPPED_TEMPLATES.items()]


def _apply_overlay_clip(mesh: trimesh.Trimesh, clip: str | None) -> trimesh.Trimesh:
    """optionally clips a template mesh the same way the real pipeline clips
    a patient's mesh, using REFERENCE_TRIANGLE (or, for facial, its
    nasion-recentered counterpart) as stand-in landmarks (a template sits in
    the registered frame by definition, so its own landmarks would land
    there anyway). backs the "show template overlay" viewer feature - it
    compares against the patient's *clipped* result now, so the template
    needs the same cut to line up.

    the facial branch needs FACE_REFERENCE_TRIANGLE, not REFERENCE_TRIANGLE:
    pipeline.register() shifts the mesh an extra step for facial targets so
    the nasion sits at the origin, and REFERENCE_TRIANGLE was never adjusted
    to match that shift. using the raw triangle here clipped the template
    around z=0 while a real face-target-registered mesh's landmarks sit
    around z=-57, so the overlay landed nowhere near the actual face.

    this clips live rather than shipping separate pre-clipped template
    files, on purpose: a static "clipped_template_xy_com.ply" is exactly the
    kind of thing that silently drifts out of sync the next time
    clipping.py's cranial_clip changes (it already had - checked its actual
    bounds against a freshly-registered mesh and it was clipping ~1.2mm
    above the landmark plane instead of at it, a leftover from however it
    got generated originally, and the mismatch only became visible once the
    overlay started comparing clipped-vs-clipped instead of full-vs-full).
    computing it live means it can never go stale again.

    trim_rear_neck=False, always, for the cranial branch - not every
    shipped template was registered with center-of-mass correction baked
    into its pose (the plain "template_xy"/"clipped_template_xy", without
    the "_com" suffix, weren't). cranial_clip's rear/neck safety plane is
    hardcoded against the pose CoM correction produces (see its docstring),
    and clipping one of the non-CoM templates with that plane still active
    reproduced the exact same gouge as pipeline.analyze_cranial's
    com_translation=False bug - measured ~58mm of boundary Y-spread on
    clipped_template_xy versus <1mm clean. skipping it here costs nothing
    real: this is comparison-overlay geometry, not the measurement
    pipeline, and the sphere trim + keep_largest_component + clean_boundary
    already handle whatever stray junk a template might have without that
    plane's help."""
    if clip is None:
        return mesh
    if clip == "cranial":
        return cranial_clip(mesh, REFERENCE_TRIANGLE, trim_rear_neck=False)
    if clip == "facial":
        return facial_clip(mesh, FACE_REFERENCE_TRIANGLE)
    raise HTTPException(status_code=400, detail=f"clip must be 'cranial' or 'facial', got {clip!r}")


# these two have to come before "/{name}/mesh" below - otherwise that route's
# {name} would swallow "custom" and this code would never get reached.


@templates_router.get("/custom/mesh")
def get_custom_template_mesh(path: str, clip: str | None = None):
    """GLB export of a template mesh loaded straight from a local filesystem
    path - backs the desktop app's "remember this template for next time"
    flow (see desktop/app.py's pick_file / frontend/app.js). reads the file
    fresh every call, nothing kept server-side - the "remembering" happens
    client-side, in the frontend's localStorage.

    only makes sense because both the desktop app and the documented
    `uvicorn api.main:app` web-service launch bind to 127.0.0.1 - the
    browser and this server are always the same machine, same trust
    boundary as opening the file in Explorer already."""
    mesh_path = Path(path)
    if not mesh_path.is_file():
        raise HTTPException(status_code=400, detail=f"file not found: {path}")
    try:
        mesh = trimesh.load(mesh_path, process=False, force="mesh")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not read mesh: {exc}") from exc
    if not isinstance(mesh, trimesh.Trimesh):
        raise HTTPException(status_code=400, detail="file did not contain a single triangle mesh")
    mesh = strip_uninteresting_vertex_colors(mesh)
    mesh = _apply_overlay_clip(mesh, clip)
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@templates_router.post("/custom/upload")
async def upload_custom_template_mesh(files: list[UploadFile], clip: str | None = None):
    """GLB export of an uploaded template mesh - the plain-browser fallback
    for when there's no pywebview file dialog to remember a path with (see
    get_custom_template_mesh above). also stateless, nothing kept
    server-side beyond this one response - the browser can't remember a
    real filesystem path across restarts anyway, so there's nothing to
    persist here."""
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    primary_name, contents_by_name = _load_primary_and_resolver(files)
    mesh = _load_mesh_from_upload(primary_name, contents_by_name)
    mesh = _apply_overlay_clip(mesh, clip)
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@templates_router.get("/{name}/mesh")
def get_template_mesh(name: str, clip: str | None = None):
    """GLB export of a shipped template - used for the "show template
    overlay" viewer feature, comparing a patient's clipped result mesh
    against a reference. pass clip=cranial or clip=facial to get it clipped
    the same way live (see _apply_overlay_clip) instead of picking one of
    the separately-named clipped_template_* files, which are pre-baked and
    can (and did) drift out of sync with clipping.py."""
    if name not in SHIPPED_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"unknown template {name!r}")
    mesh = load_shipped_template(name)
    mesh = _apply_overlay_clip(mesh, clip)
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@router.post("", response_model=UploadResponse)
async def upload_mesh(files: list[UploadFile]) -> UploadResponse:
    """upload a mesh, and optionally its companion files too (.mtl + the
    texture image, for a textured .obj). obj/ply reference textures by
    filename in a separate file, not inline - so a lone .obj can't actually
    carry its texture, trimesh just quietly falls back to a blank placeholder
    image if it can't find what it's looking for. multi-select them together
    in the frontend's file picker and this sorts it out.

    this is the plain-browser path - no real filesystem path comes with an
    HTTP upload, so a session opened this way can't use /save (see
    open_mesh_from_paths for the desktop equivalent that can).
    """
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    primary_name, contents_by_name = _load_primary_and_resolver(files)
    mesh = _load_mesh_from_upload(primary_name, contents_by_name)

    session = store.create(mesh, original_filename=primary_name)
    return UploadResponse(session_id=session.id, vertex_count=len(mesh.vertices), face_count=len(mesh.faces))


@router.post("/from-paths", response_model=UploadResponse)
def open_mesh_from_paths(request: OpenFromPathsRequest) -> UploadResponse:
    """same as upload_mesh, but reads straight from local filesystem paths
    instead of an HTTP upload - the desktop app's native (multi-select) file
    dialog hands back real paths, so there's no reason to round-trip the
    bytes through a browser upload. remembers the containing folder on the
    session too, so /save can write results back next to the original file
    without asking where."""
    primary_name, contents_by_name = _load_primary_and_resolver_from_paths(request.paths)
    mesh = _load_mesh_from_upload(primary_name, contents_by_name)

    primary_path = next(p for p in request.paths if Path(p).name == primary_name)
    session = store.create(mesh, original_filename=primary_name, source_dir=Path(primary_path).parent)
    return UploadResponse(session_id=session.id, vertex_count=len(mesh.vertices), face_count=len(mesh.faces))


@router.post("/{session_id}/analyze", response_model=StatusResponse)
def start_analysis(session_id: str, request: AnalyzeRequest) -> StatusResponse:
    session = _get_session(session_id)
    landmarks = np.array([[p.x, p.y, p.z] for p in request.landmarks])
    alt_frontal = None
    if request.alt_frontal_landmark is not None:
        p = request.alt_frontal_landmark
        alt_frontal = np.array([p.x, p.y, p.z])

    clip_cfg = request.clipping
    manual_normal = list(clip_cfg.manual_plane_normal) if clip_cfg.manual_plane_normal else None
    manual_origin = list(clip_cfg.manual_plane_origin) if clip_cfg.manual_plane_origin else None
    if clip_cfg.mode == "manual" and (manual_normal is None or manual_origin is None):
        raise HTTPException(status_code=400, detail="clipping.mode='manual' needs manual_plane_normal and manual_plane_origin")

    def _run() -> dict:
        if request.target == "cranium":
            # nasion (mandatory, above) always drives the actual
            # measurements - alt_frontal (if given) only takes over the
            # displayed/saved mesh's registration+clip frame. see
            # pipeline.analyze_cranial's docstring for why these can't be
            # the same knob.
            result = pipeline.analyze_cranial(
                session.mesh,
                landmarks,
                alt_frontal_landmark=alt_frontal,
                com_translation=request.com_translation,
                clip_mode=clip_cfg.mode,
                manual_plane_normal=manual_normal,
                manual_plane_origin=manual_origin,
                n_vertices=request.harmonize.n_vertices,
                repair=request.harmonize.repair,
                repair_method=request.harmonize.repair_method,
                on_progress=session.report_progress,
            )
            session.registered_mesh = result.display_registered_mesh
            session.result_mesh = result.display_mesh
            session.nasion_result_mesh = result.nasion_mesh
            session.report_progress("done", "")
            return {
                "landmarks": result.display_landmarks,
                "craniometrics": result.craniometrics,
                "asymmetry": None,
                "request": request,
                "nasion_landmarks": result.nasion_landmarks if result.used_alt_frontal else None,
                "display_hc_polygon": result.display_hc_polygon,
                "used_alt_frontal": result.used_alt_frontal,
            }

        # facial: unaffected by alt_frontal_landmark (cranium-only, see
        # AnalyzeRequest) - single registration, same as always.
        session.nasion_result_mesh = None
        reg = pipeline.register(
            session.mesh,
            landmarks,
            target=request.target,
            com_translation=request.com_translation,
            on_progress=session.report_progress,
        )
        session.registered_mesh = reg.mesh

        harmonized = pipeline.harmonize(
            reg.mesh,
            target=request.target,
            landmarks=reg.landmarks,
            clip_mode=clip_cfg.mode,
            manual_plane_normal=manual_normal,
            manual_plane_origin=manual_origin,
            n_vertices=request.harmonize.n_vertices,
            repair=request.harmonize.repair,
            repair_method=request.harmonize.repair_method,
            com_translation=request.com_translation,
            on_progress=session.report_progress,
        )
        session.result_mesh = harmonized

        session.report_progress("analyze", "computing measurements")
        from craniumpy_core.asymmetry import calculate_asymmetry

        asymmetry = calculate_asymmetry(harmonized)
        session.report_progress("done", "")

        return {
            "landmarks": reg.landmarks,
            "craniometrics": None,
            "asymmetry": asymmetry,
            "request": request,
            "nasion_landmarks": None,
            "display_hc_polygon": None,
            "used_alt_frontal": False,
        }

    try:
        store.run_job(session, _run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StatusResponse(status="running", progress=None)


@router.get("/{session_id}/status", response_model=StatusResponse)
def get_status(session_id: str) -> StatusResponse:
    session = _get_session(session_id)
    from api.schemas import ProgressInfo

    progress = ProgressInfo(stage=session.progress["stage"], detail=session.progress["detail"])
    return StatusResponse(status=session.job_status, error=session.job_error, progress=progress)


@router.get("/{session_id}/results", response_model=ResultsResponse)
def get_results(session_id: str) -> ResultsResponse:
    session = _get_session(session_id)
    if session.job_status != "done" or session.result is None:
        raise HTTPException(status_code=409, detail=f"no completed analysis yet (status: {session.job_status})")

    r = session.result
    craniometrics = None
    if r["craniometrics"] is not None:
        m = r["craniometrics"]
        # precomputed at analyze time, already in whatever frame
        # session.result_mesh is actually in (see pipeline.analyze_cranial) -
        # recomputing it live here the way this used to work would slice
        # the WRONG mesh at a Y that only means anything in the nasion
        # frame, once an alt_frontal_landmark is in play.
        polygon = r["display_hc_polygon"]
        craniometrics = CraniometricsResponse(
            slice_height=m.slice_height,
            depth_mm=m.depth_mm,
            breadth_mm=m.breadth_mm,
            cephalic_index=m.cephalic_index,
            circumference_cm=m.circumference_cm,
            mesh_volume_cc=float(m.mesh_volume_cc),
            hc_slice_polygon=[LandmarkPoint(x=p[0], y=p[1], z=p[2]) for p in (polygon if polygon is not None else [])],
        )

    asymmetry = None
    if r["asymmetry"] is not None:
        asymmetry = AsymmetryResponse(
            mean_asymmetry_index=r["asymmetry"].mean_asymmetry_index,
            heatmap=r["asymmetry"].heatmap.tolist(),
        )

    return ResultsResponse(
        landmarks=[LandmarkPoint(x=p[0], y=p[1], z=p[2]) for p in r["landmarks"]],
        vertex_count=len(session.result_mesh.vertices),
        craniometrics=craniometrics,
        asymmetry=asymmetry,
        used_alt_frontal=r["used_alt_frontal"],
    )


@router.get("/{session_id}/mesh/{stage}")
def export_mesh(session_id: str, stage: str):
    session = _get_session(session_id)
    if stage == "original":
        mesh = session.mesh
    elif stage == "registered":
        if session.registered_mesh is None:
            raise HTTPException(status_code=409, detail="no registered mesh yet -- run /analyze first")
        mesh = session.registered_mesh
    elif stage == "result":
        if session.result_mesh is None:
            raise HTTPException(status_code=409, detail="no result mesh yet -- run /analyze first")
        mesh = session.result_mesh
    else:
        raise HTTPException(status_code=400, detail="stage must be 'original', 'registered', or 'result'")

    # include_normals=True matters here - trimesh leaves the NORMAL accessor
    # out entirely otherwise (checked the raw glTF JSON myself, attributes
    # was just {"POSITION": ...}). without normals the mesh renders solid
    # black in the browser no matter what color it's supposed to be.
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@router.get("/{session_id}/bundle")
def download_results_bundle(session_id: str):
    session = _get_session(session_id)
    if session.job_status != "done" or session.result is None or session.registered_mesh is None:
        raise HTTPException(status_code=409, detail=f"no completed analysis yet (status: {session.job_status})")

    r = session.result
    request: AnalyzeRequest = r["request"]
    config = request.model_dump()
    folder_name = results_folder_name(session.original_filename, request.target, config)

    zip_bytes = build_results_bundle(
        original_filename=session.original_filename,
        registered_mesh=session.registered_mesh,
        final_mesh=session.result_mesh,
        landmarks=r["landmarks"],
        target=request.target,
        craniometrics=r["craniometrics"],
        asymmetry=r["asymmetry"],
        config=config,
        nasion_mesh=session.nasion_result_mesh,
        nasion_landmarks=r["nasion_landmarks"],
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'},
    )


@router.post("/{session_id}/save", response_model=SaveResultsResponse)
def save_results_to_source_folder(session_id: str) -> SaveResultsResponse:
    """writes results straight into a CP_{stem}_{C|F}_{3|4}[_CoM]/ folder
    next to the original mesh file (see results_bundle.results_folder_name)
    - only works for a session opened via open_mesh_from_paths (desktop
    app, native file picker), since that's the only case where we actually
    know a real folder to write into. the frontend falls back to the zip
    download (/bundle) when this 400s."""
    session = _get_session(session_id)
    if session.source_dir is None:
        raise HTTPException(
            status_code=400,
            detail="this session wasn't opened from a real file path, nowhere to save to - use /bundle instead",
        )
    if session.job_status != "done" or session.result is None or session.registered_mesh is None:
        raise HTTPException(status_code=409, detail=f"no completed analysis yet (status: {session.job_status})")

    r = session.result
    request: AnalyzeRequest = r["request"]

    results_dir = write_results_to_folder(
        dest_dir=session.source_dir,
        original_filename=session.original_filename,
        registered_mesh=session.registered_mesh,
        final_mesh=session.result_mesh,
        landmarks=r["landmarks"],
        target=request.target,
        craniometrics=r["craniometrics"],
        asymmetry=r["asymmetry"],
        config=request.model_dump(),
        nasion_mesh=session.nasion_result_mesh,
        nasion_landmarks=r["nasion_landmarks"],
    )
    return SaveResultsResponse(saved_to=str(results_dir))
