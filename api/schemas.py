from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LandmarkPoint(BaseModel):
    x: float
    y: float
    z: float


class ClippingConfig(BaseModel):
    # leave as None to get the usual clip for the target (cranial for cranium,
    # facial for face). "manual" needs both plane fields below - comes from
    # the plane widget in the viewer
    mode: Literal["cranial", "facial", "manual"] | None = None
    manual_plane_normal: tuple[float, float, float] | None = None
    manual_plane_origin: tuple[float, float, float] | None = None


class HarmonizeConfig(BaseModel):
    n_vertices: int | None = 10_000
    repair: bool = True
    repair_method: Literal["pymeshfix", "trimesh"] = "pymeshfix"


class AnalyzeRequest(BaseModel):
    target: Literal["cranium", "face"] = "cranium"
    # sellion, left_tragus, right_tragus in that order, in the mesh's own
    # coordinates. always required now, always picked manually - see
    # pipeline.py for why I dropped automatic detection
    landmarks: list[LandmarkPoint] = Field(min_length=3, max_length=3)
    # optional, cranium-only: an alternate frontal point (e.g. subnasale)
    # that takes over as the registration/clip/display frame for
    # everything shown/saved, while sellion (still mandatory above) stays
    # the anchor for the actual measurements and the saved 2D figure - see
    # craniumpy_core.pipeline.analyze_cranial for why sellion can't just be
    # swapped out for this instead of adding it alongside.
    alt_frontal_landmark: LandmarkPoint | None = None
    com_translation: bool = True
    clipping: ClippingConfig = ClippingConfig()
    harmonize: HarmonizeConfig = HarmonizeConfig()


class AlignRequest(BaseModel):
    """the "align" stage's request body - pure rigid registration
    (landmark-triangle alignment), nothing else. no com_translation, no
    repair, no clipping - those all happen together as one committed step
    when "run pipeline" is pressed (see ClipRequest/RunRequest)."""

    target: Literal["cranium", "face"] = "cranium"
    landmarks: list[LandmarkPoint] = Field(min_length=3, max_length=3)
    alt_frontal_landmark: LandmarkPoint | None = None


class RegisteredTransformResponse(BaseModel):
    """the rigid transform (rotation + translation) the last successful
    /align produced for the currently-displayed frame - lets the frontend
    convert a landmark position between the raw upload's coordinates and
    the aligned mesh's coordinates without re-deriving the fit itself
    (see landmark_align/RigidTransform.apply: aligned = raw @ R.T + t).
    used so "adjust picks" can let you drag a landmark on the aligned
    mesh and still send the right raw-frame value back to /align or
    /clip afterward."""

    rotation: list[list[float]]  # 3x3, row-major, matches RigidTransform.rotation
    translation: list[float]  # 3


class ClipRequest(BaseModel):
    """the "Clip" stage's request body - register + repair + clip +
    boundary cleanup, no resample. same fields AnalyzeRequest carried for
    that part of the job; repair/repair_method moved up from the old
    nested HarmonizeConfig since resample no longer happens here (see
    RunRequest) - repair belongs with clipping now, not with resample."""

    target: Literal["cranium", "face"] = "cranium"
    landmarks: list[LandmarkPoint] = Field(min_length=3, max_length=3)
    alt_frontal_landmark: LandmarkPoint | None = None
    com_translation: bool = True
    clipping: ClippingConfig = ClippingConfig()
    repair: bool = True
    repair_method: Literal["pymeshfix", "trimesh"] = "pymeshfix"


class NicpConfig(BaseModel):
    """opts into non-rigid template fitting instead of a plain resample -
    see craniumpy_core.registration.nicp. template is a shipped template
    name (see template_registry.SHIPPED_TEMPLATES); custom_template_path
    is a real filesystem path instead (desktop app only, same
    path-resolution the template-overlay viewer feature already uses) -
    exactly one of the two should be given. alpha_start/alpha_end/
    alpha_steps reconstruct nicp()'s alphas stiffness schedule
    (np.linspace(alpha_start, alpha_end, alpha_steps)) - exposed as three
    numbers instead of a raw array since that's what a form field can
    actually hold."""

    template: str | None = None
    custom_template_path: str | None = None
    alpha_start: float = 200.0
    alpha_end: float = 1.0
    alpha_steps: int = 20
    gamma: float = 1.0
    dist_threshold: float = 10.0
    inner_iters: int = 3


class RunRequest(BaseModel):
    """the "Run" stage's request body - resample + measure, on whatever
    /clip already produced. no target/landmarks/clipping here - those
    were already committed by /clip.

    nicp, when given, replaces the plain resample entirely (n_vertices/
    resample_method are ignored) - see NicpConfig."""

    n_vertices: int | None = 10_000
    resample_method: Literal["quadric", "voronoi"] = "quadric"
    nicp: NicpConfig | None = None


class ClipUndoResponse(BaseModel):
    # False if there was nothing to undo (no clip had been run yet) - not
    # an error, just a no-op.
    reverted: bool


class TemplateInfo(BaseModel):
    name: str
    description: str


class UploadResponse(BaseModel):
    session_id: str
    vertex_count: int
    face_count: int


class OpenFromPathsRequest(BaseModel):
    # absolute local filesystem paths - the mesh plus, optionally, its
    # .mtl/texture companions, all picked in one go by the desktop app's
    # native (multi-select) file dialog. see api/routers/mesh.py's
    # open_mesh_from_paths and desktop/app.py's pick_file.
    paths: list[str] = Field(min_length=1)


class PatientMetadata(BaseModel):
    """patient/visit fields the user fills in (or leaves blank) in the
    sidebar form before exporting - see api/results_bundle.py's
    _metrics_row. plain optional strings, no numeric/date coercion, so
    "still included but empty when unfilled" is trivial everywhere (form,
    wire format, CSV cell) with no null-handling branches. age_imaging is
    entered in months, same unit as age_surgery_months - this app's
    cephalometrics are validated for pediatric heads."""

    file_name: str = ""
    file_path: str = ""
    patient_id: str = ""
    sex: str = ""
    date_imaging: str = ""
    age_imaging: str = ""
    treatment: str = ""
    age_surgery_months: str = ""
    free_variable: str = ""


class SaveRequest(BaseModel):
    """body for /save, /save/meshes, /save/analysis. dest_dir, when given,
    overrides the default destination (next to the original mesh file,
    session.source_dir) - the desktop app's "change save folder..." control
    (a native folder-picker dialog) is the only thing that ever sets this;
    left out (None), the save goes wherever it always has.

    metadata rides along on /save and /save/analysis so the summary
    spreadsheet/PDF the export produces has the patient/visit fields baked
    in - see api/results_bundle.py's _build_analysis_files.
    cohort_xlsx_path, when given, additionally upserts this session's row
    into that external spreadsheet (desktop-only - see
    write_analysis_to_folder's cohort_xlsx_path param; a browser zip
    download has no persistent file to append to)."""

    dest_dir: str | None = None
    metadata: PatientMetadata = PatientMetadata()
    cohort_xlsx_path: str | None = None


class SaveResultsResponse(BaseModel):
    saved_to: str


class ProgressInfo(BaseModel):
    stage: str
    detail: str
    # only meaningful for "nicp"'s stiffness-step-by-step progress - lets the
    # frontend show a real percentage instead of the stage guessing one.
    current: int | None = None
    total: int | None = None


class StatusResponse(BaseModel):
    status: Literal["idle", "running", "done", "error"]
    error: str | None = None
    progress: ProgressInfo | None = None


class CraniometricsResponse(BaseModel):
    slice_height: float
    depth_mm: float
    breadth_mm: float
    cephalic_index: float
    circumference_cm: float
    mesh_volume_cc: float
    # the HC slice outline, so the viewer can draw the red line overlay -
    # see craniumpy_core.craniometrics.hc_slice_polygon
    hc_slice_polygon: list[LandmarkPoint]
    # the 4 optima the BPD/OFD spans run between - same points the saved
    # 2D figure marks (see api/results_bundle.py's _measurement_figure) -
    # so the live viewer can draw the same two lines.
    front_opt: LandmarkPoint
    occ_opt: LandmarkPoint
    lh_opt: LandmarkPoint
    rh_opt: LandmarkPoint


class AsymmetryResponse(BaseModel):
    mean_asymmetry_index: float
    # one signed distance (mm) per vertex of the result mesh, same order -
    # see craniumpy_core.asymmetry.calculate_asymmetry. zeroed out on one
    # half by design (see that module's docstring), for the viewer's
    # blue(dent)/red(protruded) heatmap overlay.
    heatmap: list[float]


class Point2D(BaseModel):
    """a point in the metopic module's own 2D forehead-contour plane - x is
    left-right, z is depth (same convention as craniumpy_core.metopic's
    module docstring). paired with MetopicResponse.slice_height, the
    viewer can place one of these back into 3D as (x, slice_height, z)."""

    x: float
    z: float


class MetopicResponse(BaseModel):
    """the whole craniumpy_core.metopic.MetopicResult, facial-target only -
    see that module for what each field means and craniumpy_core.pipeline.
    hc_slice_height_facial_frame for why slice_height here is always the
    same plane a cranial run on this same patient would use."""

    slice_height: float
    contour: list[Point2D]
    arc_length: list[float]
    normalized_arc_length: list[float]
    midline_u: float
    parabola_a: float
    parabola_c: float
    deviation_profile: list[float]
    gradient_profile: list[float]
    curvature_profile: list[float]

    frontal_angle_deg: float
    frontal_angle_points: list[Point2D]  # [M, L, R]
    forehead_width_mm: float

    midline_curvature_concentration: float
    midline_max_curvature: float
    midline_max_curvature_position: float

    ridge_protrusion_mm: float
    ridge_protrusion_position: float
    ridge_area_mm2: float
    ridge_area_normalized: float

    left_temporal_hollowing: float
    right_temporal_hollowing: float
    mean_temporal_hollowing: float
    left_max_temporal_depth_mm: float
    right_max_temporal_depth_mm: float

    parabolic_deviation_index: float

    # (u_start, u_end) along normalized_arc_length, for drawing the region
    # shading the same way the exported figure does - see
    # craniumpy_core.metopic's CENTRAL_WINDOW_HALF_WIDTH_U etc.
    central_window: tuple[float, float]
    left_temporal_window: tuple[float, float]
    right_temporal_window: tuple[float, float]


class FrontalBossingResponse(BaseModel):
    """how much the forehead bulges forward, measured in the sagittal
    (midline) plane through sellion - see
    craniumpy_core.craniometrics.frontal_bossing for the actual geometry
    and sign convention. computed the same way for cranial and facial
    targets alike, since it's defined purely relative to sellion's own
    position rather than any shared plane/height."""

    angle_deg: float
    sellion: LandmarkPoint
    frontal_point: LandmarkPoint
    # the sagittal contour, so the viewer can draw the same profile line
    # the exported figure shows.
    profile: list[LandmarkPoint]
    # unit direction the angle was measured against, for the viewer's dashed
    # reference line. this is the sellion-tragus plane's own depth axis, NOT
    # necessarily +z of the frame these points are in: with a secondary
    # frontal landmark the displayed frame is rotated relative to the frame
    # the angle was measured in, so drawing the reference along +z there
    # would show an angle that doesn't match angle_deg (see
    # craniumpy_core.pipeline.measure_cranial).
    horizontal: LandmarkPoint


class ResultsResponse(BaseModel):
    landmarks: list[LandmarkPoint]
    vertex_count: int
    craniometrics: CraniometricsResponse | None = None
    asymmetry: AsymmetryResponse | None = None
    metopic: MetopicResponse | None = None
    frontal_bossing: FrontalBossingResponse | None = None
    # True when an alt_frontal_landmark was given and the shown/saved mesh
    # is in that frame instead of the sellion one - see AnalyzeRequest
    used_alt_frontal: bool = False
