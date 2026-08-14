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
from craniumpy_core.asymmetry import calculate_asymmetry
from craniumpy_core.io import strip_uninteresting_vertex_colors
from craniumpy_core.template_registry import SHIPPED_TEMPLATES, load_shipped_template
from api.results_bundle import build_results_bundle, results_folder_name, write_results_to_folder
from api.schemas import (
    AlignRequest,
    AnalyzeRequest,
    AsymmetryResponse,
    ClipRequest,
    ClipUndoResponse,
    CraniometricsResponse,
    HarmonizeConfig,
    LandmarkPoint,
    OpenFromPathsRequest,
    RegisteredTransformResponse,
    ResultsResponse,
    RunRequest,
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


def _pure_align(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    alt_frontal: np.ndarray | None,
    target: str,
    on_progress=None,
) -> pipeline.RegistrationResult:
    """the landmark-triangle-only registration shared by /align and /clip -
    no repair, no center-of-mass nudge. /align uses this directly as its
    whole job; /clip uses it too (on the raw, unrepaired mesh) purely to
    populate session.aligned_mesh, independently of whatever repaired +
    CoM-nudged registration it does for the actual clip - see
    Session.aligned_mesh."""
    if target == "cranium" and alt_frontal is not None:
        alt_landmarks = np.array([alt_frontal, landmarks[1], landmarks[2]])
        return pipeline.register(mesh, alt_landmarks, target="cranium", com_translation=False, on_progress=on_progress)
    return pipeline.register(mesh, landmarks, target=target, com_translation=False, on_progress=on_progress)


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


# these two have to come before "/{name}/mesh" below - otherwise that route's
# {name} would swallow "custom" and this code would never get reached.


@templates_router.get("/custom/mesh")
def get_custom_template_mesh(path: str):
    """GLB export of a template mesh loaded straight from a local filesystem
    path - backs the desktop app's "remember this template for next time"
    flow (see desktop/app.py's pick_file / frontend/app.js). reads the file
    fresh every call, nothing kept server-side - the "remembering" happens
    client-side, in the frontend's localStorage. served as-is, whatever's
    actually in the file - the "show template overlay" viewer feature is a
    reference comparison, not a copy of the patient's own clip.

    fine to trust a raw local path here since both the desktop app and the
    web-service launch bind to 127.0.0.1 - browser and server are always the
    same machine, same trust boundary as opening the file in Explorer."""
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
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@templates_router.post("/custom/upload")
async def upload_custom_template_mesh(files: list[UploadFile]):
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
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@templates_router.get("/{name}/mesh")
def get_template_mesh(name: str):
    """GLB export of a shipped template, as-is - used for the "show
    template overlay" viewer feature, comparing a patient's result mesh
    against a reference."""
    if name not in SHIPPED_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"unknown template {name!r}")
    mesh = load_shipped_template(name)
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


@router.post("/{session_id}/align", response_model=StatusResponse)
def start_align(session_id: str, request: AlignRequest) -> StatusResponse:
    """pure rigid registration - landmark-triangle alignment only. no
    center-of-mass nudge, no repair, no clip - just fast enough to
    preview instantly and to gate "run pipeline" behind a sane
    registration. repair/clip/resample/CoM-correction all happen
    together later, as one committed step, when /clip then /run are
    triggered ("run pipeline" - see start_clip/start_run).

    also stores the rigid transform that produced the displayed frame
    (session.registered_transform), so the frontend can convert a
    landmark position between raw and aligned coordinates for "adjust
    picks" without re-deriving the fit itself - see
    RegisteredTransformResponse."""
    session = _get_session(session_id)
    landmarks = np.array([[p.x, p.y, p.z] for p in request.landmarks])
    alt_frontal = None
    if request.alt_frontal_landmark is not None:
        p = request.alt_frontal_landmark
        alt_frontal = np.array([p.x, p.y, p.z])

    def _run() -> None:
        session.clear_clip_result()

        sellion_reg = pipeline.register(
            session.mesh, landmarks, target=request.target, com_translation=False, on_progress=session.report_progress
        )
        session.sellion_registered_mesh = sellion_reg.mesh
        session.sellion_registered_landmarks = sellion_reg.landmarks

        if request.target == "cranium" and alt_frontal is not None:
            alt_reg = _pure_align(session.mesh, landmarks, alt_frontal, request.target, session.report_progress)
            session.registered_mesh = alt_reg.mesh
            session.registered_landmarks = alt_reg.landmarks
            session.registered_transform = alt_reg.transform
        else:
            session.registered_mesh = sellion_reg.mesh
            session.registered_landmarks = sellion_reg.landmarks
            session.registered_transform = sellion_reg.transform

        # kept separately from registered_mesh, which /clip below is about
        # to overwrite with a repaired + CoM-nudged version - this is what
        # gets saved as _rg.ply, so it has to survive that overwrite.
        session.aligned_mesh = session.registered_mesh

        session.report_progress("done", "")
        return None

    try:
        store.run_job(session, _run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StatusResponse(status="running", progress=None)


@router.get("/{session_id}/registered-transform", response_model=RegisteredTransformResponse)
def get_registered_transform(session_id: str) -> RegisteredTransformResponse:
    session = _get_session(session_id)
    if session.registered_transform is None:
        raise HTTPException(status_code=409, detail="no registration yet -- run /align first")
    transform = session.registered_transform
    return RegisteredTransformResponse(
        rotation=np.asarray(transform.rotation).tolist(), translation=np.asarray(transform.translation).tolist()
    )


@router.post("/{session_id}/clip", response_model=StatusResponse)
def start_clip(session_id: str, request: ClipRequest) -> StatusResponse:
    """register + repair + clip + boundary cleanup, no resample, no
    measurement - the fast-ish, re-runnable half of what used to be one
    monolithic /analyze. repeated calls (different plane, different clip
    mode, toggling alt-frontal) reuse session.repaired_mesh instead of
    re-running pymeshfix every time - see Session.repaired_mesh and
    pipeline.register_and_clip_cranial's docstring. always invalidates
    whatever a previous /clip or /run produced (see
    Session.clear_clip_result), so /run must be called again afterward.

    for cranial/facial clip modes (not manual, whose plane is arbitrary and
    unrelated to the landmarks), repair runs on a rough landmark-based
    pre-clip of the raw mesh rather than the whole thing - see
    pipeline.rough_bounding_clip. cuts repair's runtime on a large scan a
    lot, since it's the slow part and now has far less to chew on."""
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
        session.clear_clip_result()

        # always (re)computed here, from the raw mesh, independently of
        # whatever repaired + CoM-nudged registration this same call does
        # below for the actual clip - this is what gets saved as _rg.ply.
        # recomputed rather than trusting a prior /align call so it can't
        # go stale against this request's landmarks (also means /clip
        # works standalone, without /align ever having been called).
        session.aligned_mesh = _pure_align(session.mesh, landmarks, alt_frontal, request.target, session.report_progress).mesh

        if request.repair:
            cache_key = (
                request.repair_method,
                request.target,
                clip_cfg.mode,
                tuple(landmarks.flatten().tolist()),
                tuple(alt_frontal.tolist()) if alt_frontal is not None else None,
            )
            if session.repaired_mesh is None or session.repaired_mesh_cache_key != cache_key:
                repair_input = session.mesh
                if clip_cfg.mode != "manual":
                    session.report_progress("repair", "rough pre-clip before repair")
                    repair_input = pipeline.rough_bounding_clip(session.mesh, landmarks, alt_frontal_landmark=alt_frontal)
                session.report_progress("repair", f"repairing mesh ({request.repair_method})")
                session.repaired_mesh = pipeline.repair_mesh(repair_input, method=request.repair_method)
                session.repaired_mesh_cache_key = cache_key
        else:
            session.repaired_mesh = session.mesh
            session.repaired_mesh_cache_key = None

        if request.target == "cranium":
            # sellion (mandatory, above) always drives the actual
            # measurements - alt_frontal (if given) only takes over the
            # displayed/saved mesh's registration+clip frame. see
            # pipeline.register_and_clip_cranial's docstring for why
            # these can't be the same knob.
            clip_result = pipeline.register_and_clip_cranial(
                session.repaired_mesh,
                landmarks,
                alt_frontal_landmark=alt_frontal,
                com_translation=request.com_translation,
                clip_mode=clip_cfg.mode,
                manual_plane_normal=manual_normal,
                manual_plane_origin=manual_origin,
                on_progress=session.report_progress,
            )
            session.sellion_registered_mesh = clip_result.sellion_registered_mesh
            session.sellion_registered_landmarks = clip_result.sellion_registered_landmarks
            session.registered_mesh = clip_result.display_registered_mesh
            session.registered_landmarks = clip_result.display_registered_landmarks
            session.sellion_clipped_mesh = clip_result.sellion_clipped_mesh
            session.clipped_mesh = clip_result.display_clipped_mesh
            session.used_alt_frontal = clip_result.used_alt_frontal
        else:
            # facial: unaffected by alt_frontal_landmark (cranium-only,
            # see ClipRequest) - single registration, same as always.
            reg = pipeline.register(
                session.repaired_mesh,
                landmarks,
                target=request.target,
                com_translation=request.com_translation,
                on_progress=session.report_progress,
            )
            session.sellion_registered_mesh = None
            session.sellion_registered_landmarks = None
            session.registered_mesh = reg.mesh
            session.registered_landmarks = reg.landmarks
            session.used_alt_frontal = False

            clipped = pipeline.harmonize(
                reg.mesh,
                target=request.target,
                landmarks=reg.landmarks,
                clip_mode=clip_cfg.mode,
                manual_plane_normal=manual_normal,
                manual_plane_origin=manual_origin,
                n_vertices=None,
                repair=False,
                com_translation=request.com_translation,
                on_progress=session.report_progress,
            )
            session.sellion_clipped_mesh = None
            session.clipped_mesh = clipped

        session.last_clip_config = request
        session.report_progress("done", "")
        return None

    try:
        store.run_job(session, _run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StatusResponse(status="running", progress=None)


@router.post("/{session_id}/clip/undo", response_model=ClipUndoResponse)
def undo_clip(session_id: str) -> ClipUndoResponse:
    """synchronous, no job - reverts to whatever /clip's last registered
    (pre-clip) mesh was, discarding the clip attempt so a different plane
    can be tried. single-level revert, no history - a second undo in a
    row is just a no-op (reverted=False)."""
    session = _get_session(session_id)
    if session.job_status == "running":
        raise HTTPException(status_code=409, detail="a job is already running for this session")
    had_clip = session.clipped_mesh is not None
    session.clear_clip_result()
    return ClipUndoResponse(reverted=had_clip)


@router.post("/{session_id}/run", response_model=StatusResponse)
def start_run(session_id: str, request: RunRequest) -> StatusResponse:
    """resample + measure, on whatever /clip already produced - the part
    of the old monolithic /analyze that's actually cheap to redo, now
    decoupled from repair+clip so tweaking n_vertices doesn't have to
    repeat those either."""
    session = _get_session(session_id)
    if session.clipped_mesh is None or session.last_clip_config is None:
        raise HTTPException(status_code=409, detail="no clipped mesh yet -- run /clip first")

    clip_request: ClipRequest = session.last_clip_config

    def _run() -> dict:
        analyze_request = AnalyzeRequest(
            target=clip_request.target,
            landmarks=clip_request.landmarks,
            alt_frontal_landmark=clip_request.alt_frontal_landmark,
            com_translation=clip_request.com_translation,
            clipping=clip_request.clipping,
            harmonize=HarmonizeConfig(
                n_vertices=request.n_vertices,
                repair=clip_request.repair,
                repair_method=clip_request.repair_method,
            ),
        )

        if clip_request.target == "cranium":
            clip_result = pipeline.CranialClipResult(
                sellion_registered_mesh=session.sellion_registered_mesh,
                sellion_registered_landmarks=session.sellion_registered_landmarks,
                display_registered_mesh=session.registered_mesh,
                display_registered_landmarks=session.registered_landmarks,
                sellion_clipped_mesh=session.sellion_clipped_mesh,
                display_clipped_mesh=session.clipped_mesh,
                used_alt_frontal=session.used_alt_frontal,
            )
            result = pipeline.measure_cranial(
                clip_result,
                com_translation=clip_request.com_translation,
                n_vertices=request.n_vertices,
                resample_method=request.resample_method,
                on_progress=session.report_progress,
            )
            session.result_mesh = result.display_mesh
            session.sellion_result_mesh = result.sellion_mesh
            session.report_progress("done", "")
            return {
                "landmarks": result.display_landmarks,
                "craniometrics": result.craniometrics,
                "asymmetry": None,
                "request": analyze_request,
                "sellion_landmarks": result.sellion_landmarks if result.used_alt_frontal else None,
                "display_hc_polygon": result.display_hc_polygon,
                "display_bpd_ofd_points": result.display_bpd_ofd_points,
                "used_alt_frontal": result.used_alt_frontal,
            }

        # facial: no alt-frontal, no CoM recenter tail (harmonize()'s
        # recenter step is cranium-only) - resample then measure.
        session.sellion_result_mesh = None
        if request.n_vertices is not None:
            session.report_progress("resample", f"resampling to {request.n_vertices} vertices ({request.resample_method})")
            result_mesh = pipeline.resample_mesh(
                session.clipped_mesh, n_vertices=request.n_vertices, method=request.resample_method
            )
        else:
            result_mesh = session.clipped_mesh
        session.result_mesh = result_mesh

        session.report_progress("analyze", "computing measurements")
        asymmetry = calculate_asymmetry(result_mesh)
        session.report_progress("done", "")

        return {
            "landmarks": session.registered_landmarks,
            "craniometrics": None,
            "asymmetry": asymmetry,
            "request": analyze_request,
            "sellion_landmarks": None,
            "display_hc_polygon": None,
            "display_bpd_ofd_points": None,
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
        # recomputing it live here would slice the wrong mesh at a Y that
        # only means anything in the sellion frame, once an alt_frontal_landmark
        # is in play.
        polygon = r["display_hc_polygon"]
        front_opt, occ_opt, lh_opt, rh_opt = r["display_bpd_ofd_points"]
        craniometrics = CraniometricsResponse(
            slice_height=m.slice_height,
            depth_mm=m.depth_mm,
            breadth_mm=m.breadth_mm,
            cephalic_index=m.cephalic_index,
            circumference_cm=m.circumference_cm,
            mesh_volume_cc=float(m.mesh_volume_cc),
            hc_slice_polygon=[LandmarkPoint(x=p[0], y=p[1], z=p[2]) for p in (polygon if polygon is not None else [])],
            front_opt=LandmarkPoint(x=front_opt[0], y=front_opt[1], z=front_opt[2]),
            occ_opt=LandmarkPoint(x=occ_opt[0], y=occ_opt[1], z=occ_opt[2]),
            lh_opt=LandmarkPoint(x=lh_opt[0], y=lh_opt[1], z=lh_opt[2]),
            rh_opt=LandmarkPoint(x=rh_opt[0], y=rh_opt[1], z=rh_opt[2]),
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
            raise HTTPException(status_code=409, detail="no registered mesh yet -- run /align first")
        mesh = session.registered_mesh
    elif stage == "clipped":
        if session.clipped_mesh is None:
            raise HTTPException(status_code=409, detail="no clipped mesh yet -- run /clip first")
        mesh = session.clipped_mesh
    elif stage == "result":
        if session.result_mesh is None:
            raise HTTPException(status_code=409, detail="no result mesh yet -- run /run first")
        mesh = session.result_mesh
    else:
        raise HTTPException(status_code=400, detail="stage must be 'original', 'registered', 'clipped', or 'result'")

    # include_normals=True matters - trimesh leaves the NORMAL accessor out
    # entirely otherwise, and without normals the mesh renders solid black
    # in the browser no matter what color it's supposed to be.
    glb_bytes = mesh.export(file_type="glb", include_normals=True)
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@router.get("/{session_id}/bundle")
def download_results_bundle(session_id: str):
    session = _get_session(session_id)
    if session.job_status != "done" or session.result is None or session.aligned_mesh is None:
        raise HTTPException(status_code=409, detail=f"no completed analysis yet (status: {session.job_status})")

    r = session.result
    request: AnalyzeRequest = r["request"]
    config = request.model_dump()
    folder_name = results_folder_name(session.original_filename, request.target, config)

    zip_bytes = build_results_bundle(
        original_filename=session.original_filename,
        registered_mesh=session.aligned_mesh,
        final_mesh=session.result_mesh,
        landmarks=r["landmarks"],
        target=request.target,
        craniometrics=r["craniometrics"],
        asymmetry=r["asymmetry"],
        config=config,
        sellion_mesh=session.sellion_result_mesh,
        sellion_landmarks=r["sellion_landmarks"],
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
    if session.job_status != "done" or session.result is None or session.aligned_mesh is None:
        raise HTTPException(status_code=409, detail=f"no completed analysis yet (status: {session.job_status})")

    r = session.result
    request: AnalyzeRequest = r["request"]

    results_dir = write_results_to_folder(
        dest_dir=session.source_dir,
        original_filename=session.original_filename,
        registered_mesh=session.aligned_mesh,
        final_mesh=session.result_mesh,
        landmarks=r["landmarks"],
        target=request.target,
        craniometrics=r["craniometrics"],
        asymmetry=r["asymmetry"],
        config=request.model_dump(),
        sellion_mesh=session.sellion_result_mesh,
        sellion_landmarks=r["sellion_landmarks"],
    )
    return SaveResultsResponse(saved_to=str(results_dir))
