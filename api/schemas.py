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


class MeasureAsRegisteredRequest(BaseModel):
    """body for /measure-registered - the "skip preprocessing" shortcut.
    the uploaded mesh is treated as already sitting in this app's canonical
    registered frame (same assumption craniumpy_core.cohort.measure_mean_shape
    already makes for the Longitudinal workspace's own "already registered"
    fast path), with no landmark picking or /align+/clip+/run needed."""

    target: Literal["cranium", "face"] = "cranium"


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


class SwitchTargetRequest(BaseModel):
    target: Literal["cranium", "face"]


class SwitchTargetResponse(BaseModel):
    """what the frontend needs to redraw the restored (or freshly blank)
    scene without recomputing anything - see api/sessions.py's
    Session.switch_active_target. restored=False means new_target has never
    been aligned/clipped/run this session, so the frontend's own per-target
    UI snapshot (if any) should be discarded too rather than reapplied
    against backend fields that no longer describe it."""

    restored: bool
    align_succeeded: bool
    pipeline_ran: bool
    has_nicp_result: bool
    used_alt_frontal: bool


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
    wire format, CSV cell) with no null-handling branches. age_imaging and
    age_intervention_months are both in months (this app's cephalometrics
    are validated for pediatric heads) and are auto-computed client-side
    from date_of_birth whenever both it and the relevant date are given
    (see PatientMetadataForm.jsx) - still plain editable strings here,
    since a caller with no date_of_birth on file can still type an age
    directly."""

    file_name: str = ""
    file_path: str = ""
    patient_id: str = ""
    date_of_birth: str = ""
    diagnosis: str = ""
    sex: str = ""
    date_imaging: str = ""
    age_imaging: str = ""
    # "t0" (initial image) or "t1".."t9" (a follow-up image, its sequence
    # number picked from a fixed dropdown - see PatientMetadataForm.jsx's
    # timing selector), or "" (unspecified) - a single flat string, same
    # "one column, not two" reasoning surgical_status just below explains
    # for itself.
    image_timing: str = ""
    # "pre-op"/"post-op"/"no_surgery" - whether surgery had already happened
    # at the time THIS image was taken, orthogonal to image_timing above
    # (which just says which image in the sequence this is). the frontend
    # treats this as required once image_timing is non-blank (see
    # PatientMetadataForm.jsx), but it's still a plain optional string here
    # like every other field - nothing server-side actually depends on it
    # being filled in.
    surgical_status: str = ""
    treatment: str = ""
    date_of_intervention: str = ""
    age_intervention_months: str = ""
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
    download has no persistent file to append to).

    include_measurements/include_asymmetry/include_meshes are the "export
    analysis" checkboxes (see App.jsx's AnalysisPanel) - only meaningful on
    /save/analysis (the other two endpoints don't look at them). unticking
    include_measurements/include_asymmetry drops the corresponding
    craniometrics-or-metopic-and-frontal_bossing / asymmetry section from
    the report and PDF entirely (see save_analysis_to_source_folder), not
    just hides it - unticking include_meshes skips writing/zipping the mesh
    files alongside the report."""

    dest_dir: str | None = None
    metadata: PatientMetadata = PatientMetadata()
    cohort_xlsx_path: str | None = None
    include_measurements: bool = True
    include_asymmetry: bool = True
    include_meshes: bool = True


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


# --- cohort / batch-analysis workspace -------------------------------


class CohortLoadRequest(BaseModel):
    """desktop: load a cohort spreadsheet straight from a real local path
    (the native file picker's own result - see frontend/src/lib/desktop.js's
    pickExcelFileNative). same "trust a local path, browser and server are
    always the same machine" reasoning api/routers/mesh.py's
    get_custom_template_mesh already relies on."""

    path: str


class CohortDataResponse(BaseModel):
    """a loaded cohort spreadsheet, as columns + row dicts - every cell a
    plain string (see craniumpy_core.cohort.load_cohort_xlsx for why:
    per-column numeric parsing is the cohort workspace's own job, not
    something baked into the load step)."""

    columns: list[str]
    rows: list[dict[str, str]]


class CohortPatientOption(BaseModel):
    """one entry in the Per-patient sidebar's "load from cohort" dropdown -
    see results_bundle.list_cohort_patients for how this gets reconstructed
    by joining the cohort file's own id-mapping companion back to the
    shared cohort file itself."""

    patient_id: str
    date_of_birth: str = ""
    date_of_intervention: str = ""
    sex: str = ""
    diagnosis: str = ""
    treatment: str = ""


class CohortPatientsResponse(BaseModel):
    patients: list[CohortPatientOption]


class CohortStatsTestRequest(BaseModel):
    """values is {group label: that group's numeric values for one metric} -
    the cohort workspace does its own filtering/grouping/type-parsing
    client-side (fast, interactive) and only sends the backend the final
    numbers to run a real inferential test against."""

    values: dict[str, list[float]]


class CohortStatsTestResponse(BaseModel):
    """both a parametric and a rank-based (nonparametric) test result
    together, rather than the backend silently picking one - see
    api/routers/cohort.py's _run_stats_test for which pair runs for 2 vs
    3+ groups."""

    n_groups: int
    group_sizes: dict[str, int]
    test_name: str
    statistic: float
    p_value: float
    alternative_test_name: str
    alternative_statistic: float
    alternative_p_value: float


class CohortMeanShapeRequest(BaseModel):
    """mesh_paths must all be NICP-fitted to the identical template - see
    craniumpy_core.cohort.mean_shape for what happens (a clear 400, not a
    silently-wrong average) if they aren't."""

    mesh_paths: list[str] = Field(min_length=1)


class CohortMeanShapeResponse(BaseModel):
    """result_id is a short-lived handle - fetch the mesh itself via
    GET /api/cohort/mean-shape/{result_id}/mesh right after this returns,
    see api/routers/cohort.py's cache."""

    result_id: str
    vertex_count: int
    source_count: int
    # per-vertex mean distance from that vertex's own mean position (mm),
    # same length/order as the served mesh's own vertices - directly usable
    # with the viewer's existing showHeatmap overlay.
    heatmap: list[float]


class ExcludedMeshOut(BaseModel):
    path: str
    reason: str


class CohortMeanShapeQcResponse(BaseModel):
    """same shape as CohortMeanShapeResponse (and cached under the same
    result_id space - every existing /mean-shape/{id}/... endpoint works
    against a QC-computed result unchanged), plus which input meshes got
    left out of the average and why - see
    craniumpy_core.cohort.mean_shape_with_outliers."""

    result_id: str
    vertex_count: int
    source_count: int
    heatmap: list[float]
    excluded: list[ExcludedMeshOut]


class CohortReferenceDiffResponse(BaseModel):
    """signed per-vertex displacement (mm) of an already-computed mean
    shape (see CohortMeanShapeResponse.result_id) from a shipped reference
    template - positive where the mean shape sits outward of the
    reference, negative inward. see craniumpy_core.cohort.reference_diff."""

    heatmap: list[float]


class CohortMeanShapeMeasurementsResponse(BaseModel):
    """the same measurement suite the Patients workspace's Analysis tab
    shows (see ResultsResponse), run directly on an already-computed mean
    shape - see craniumpy_core.cohort.measure_mean_shape for how that's
    possible with no per-group landmark tracking. reuses the exact same
    per-metric response models as ResultsResponse, so the frontend's
    existing measurement-table/overlay code needs no separate shape for
    this. asymmetry is never None (calculate_asymmetry needs no
    landmarks); craniometrics is set only for a cranium-target group,
    metopic only for a face-target one - mirrors ResultsResponse's own
    "blank when it doesn't apply to this target" convention."""

    craniometrics: CraniometricsResponse | None = None
    asymmetry: AsymmetryResponse
    metopic: MetopicResponse | None = None
    frontal_bossing: FrontalBossingResponse | None = None


class CohortSagittalBandRequest(BaseModel):
    """mesh_paths must all be NICP-fitted to the identical template, same
    as CohortMeanShapeRequest - this is computed independently of any
    cached /mean-shape result (it needs each individual mesh, not just the
    average), so it takes the same mesh_paths list the /mean-shape call
    for this group already used, rather than a result_id."""

    mesh_paths: list[str] = Field(min_length=1)
    target: str


class CohortSagittalBandResponse(BaseModel):
    """mean +/- SD of the sagittal (midline) forehead-to-vertex depth
    profile across the group - see
    craniumpy_core.cohort.sagittal_midline_band. y is a common height grid
    (mm, ascending); mean_z/sd_z are the same length as y. this is the
    shape the Mean shape tab's 2D profile chart needs (plain numbers, not
    3D points) - see CohortSpreadBandResponse for the 3D-ribbon version of
    the same data, used by the live viewer overlay and the PDF report."""

    y: list[float]
    mean_z: list[float]
    sd_z: list[float]
    source_count: int


class CohortSpreadBandResponse(BaseModel):
    """a +/-1 SD ribbon around some mean curve on the mean shape's own
    surface, as real 3D points - see craniumpy_core.cohort.SpreadBand
    (the same shape hc_ring_band/metopic_band/sagittal_band_to_spread_band
    all return). mean/inner/outer are the same length, in order (point i
    of each corresponds to the same position along the curve) - the
    frontend's 3D viewer overlay builds a ribbon mesh directly from
    inner/outer (see three/spreadBandOverlay.js), closed says whether to
    connect the last point back to the first (True for the HC ring, False
    for the sagittal/metopic arcs)."""

    mean: list[LandmarkPoint]
    inner: list[LandmarkPoint]
    outer: list[LandmarkPoint]
    closed: bool
    source_count: int


class CohortExportSheet(BaseModel):
    """one worksheet of a cohort Excel export - title becomes the sheet
    name (sanitized/deduplicated - see api/routers/cohort.py's
    _sheet_name), columns/rows are already exactly what should appear,
    in order - the cohort workspace does its own sorting/filtering/
    formula evaluation client-side (see workspaces/cohort/lib/stats.js),
    so this is just "write these cells nicely", not a second copy of that
    logic."""

    title: str
    columns: list[str]
    rows: list[dict[str, str]]


class CohortExportRequest(BaseModel):
    """a formatted Excel workbook - one or more sheets (the Table tab
    exports one sheet of the current data; the Stratify tab exports a
    descriptive-stats sheet plus a test-result sheet when a test has been
    run) - see api/routers/cohort.py's _build_export_xlsx for the actual
    formatting (colored header, banded rows, frozen header, autosized/
    auto-numeric columns, same visual style as every other spreadsheet
    this app produces)."""

    sheets: list[CohortExportSheet] = Field(min_length=1)
    filename: str = "cohort_export.xlsx"


# --- longitudinal / follow-up workspace -------------------------------


class LongitudinalMeshRef(BaseModel):
    """points at one already-in-memory server-side mesh - either a live
    patient session's own pipeline stage, or a shipped template (for the
    "distance heatmap" overlay's custom-reference mode - see
    CompareTab.jsx). exactly one of session_id/template should be set.
    stage="original" is the Longitudinal workspace's "load pre-registered
    (NICP) file" fast path - a file the user picked that's already the
    output of a prior Patients session's NICP fit (an _rg_{C|F}N.ply),
    uploaded as a fresh session's raw mesh with no /align, /clip, or /run
    needed since it's already in this app's canonical registered frame,
    fit to a shared template."""

    session_id: str | None = None
    stage: Literal["original", "clipped", "result", "nicp_result"] = "nicp_result"
    template: str | None = None


class LongitudinalDiffRequest(BaseModel):
    mesh_a: LongitudinalMeshRef
    mesh_b: LongitudinalMeshRef


class LongitudinalDiffResponse(BaseModel):
    """signed per-vertex displacement (mm) of mesh_b from mesh_a, projected
    onto mesh_a's own vertex normals - same sign convention as
    AsymmetryResponse.heatmap (positive = mesh_b sits outward of mesh_a),
    see craniumpy_core.cohort.reference_diff. both refs must resolve to
    the same template topology (same vertex count/face connectivity) -
    comes back as a 400 otherwise, not a silently meaningless comparison."""

    heatmap: list[float]
    vertex_count: int


class LongitudinalMeasureRequest(BaseModel):
    """runs the same measurement suite the Patients workspace's Analysis
    tab shows directly on an already-registered mesh, with NO landmark
    picking or session /run needed - see
    craniumpy_core.cohort.measure_mean_shape, which works by assuming the
    mesh sits at registration.rigid.REFERENCE_TRIANGLE/
    FACE_REFERENCE_TRIANGLE (true for any mesh that went through this
    app's normal rigid registration, live session or NICP-fitted alike).
    response is CohortMeanShapeMeasurementsResponse - the same shape the
    Cohort workspace's own "measure this arbitrary mesh" endpoint already
    returns, reused as-is rather than a second near-identical schema."""

    ref: LongitudinalMeshRef
    target: Literal["cranium", "face"]


class LongitudinalReportRequest(BaseModel):
    """a two-timepoint comparison PDF - see
    api/results_bundle.longitudinal_comparison_report_pdf. include_diff
    requires mesh_a/mesh_b to be the same template topology (same
    reasoning as LongitudinalDiffRequest); set it False for two
    independently-registered (not yet NICP-fit) meshes, which still
    support a side-by-side measurements comparison, just no per-vertex
    change page."""

    mesh_a: LongitudinalMeshRef
    mesh_b: LongitudinalMeshRef
    target: Literal["cranium", "face"]
    label_a: str = "Baseline"
    label_b: str = "Follow-up"
    include_diff: bool = True


# --- Facial Anthropometrics workspace -------------------------------------


class FacialTemplateLoadRequest(BaseModel):
    """the default shipped face-nasion-origin template, or an optional
    custom one - exactly one of the two should be given (shipped_name
    defaults to the shipped face template when both are omitted)."""

    shipped_name: str | None = "template_face"
    path: str | None = None


class FacialTemplateResponse(BaseModel):
    template_id: str
    vertex_count: int
    face_count: int


class FacialPickRequest(BaseModel):
    point: LandmarkPoint


class FacialPickResponse(BaseModel):
    vertex_index: int
    point: LandmarkPoint  # the snapped position, not the raw raycast hit


class FacialMeasurementDef(BaseModel):
    """one user-defined measurement - point_ids reference keys in a
    separate {point_id: LandmarkPoint} dict (see FacialMeasurementPreviewRequest/
    FacialBatchStartRequest), not raw coordinates, since the same point can
    be corrected independently later without touching the measurement
    definition itself. color is computed once, client-side, when the
    measurement is created (see frontend/src/workspaces/facial/lib/points.js's
    colorForMeasurement) and carried through every request from then on -
    the single source of truth for "consistent unique colors," so the
    legend the frontend renders live and the one the Excel export writes
    are guaranteed to match without a second color algorithm to keep in sync."""

    id: str
    name: str
    abbreviation: str
    type: Literal["linear", "angular", "area"]
    point_ids: list[str]
    geodesic: bool = False  # linear only; ignored for angular/area
    color: str = "#4ade80"  # hex, e.g. "#4ade80"


class FacialMeasurementPreviewRequest(BaseModel):
    template_id: str
    points: dict[str, LandmarkPoint]
    measurements: list[FacialMeasurementDef]


class FacialMeasurementPreviewResponse(BaseModel):
    """render_paths/render_faces are purely visual overlay geometry (see
    api/routers/facial.py's _render_geometry) - a geodesic surface path for
    Linear/Angular, or the enclosed region's own triangle positions (a flat
    list, every 3 points one triangle) for Area - always traced along the
    mesh surface regardless of a Linear measurement's own straight/geodesic
    VALUE toggle, since a straight chord between two points on a curved face
    reads as floating off the surface. missing for a measurement whose path
    couldn't be traced (a disconnected mesh) - the frontend falls back to a
    plain straight connector between the raw landmark points in that case."""

    values: dict[str, float | None]
    value_errors: dict[str, str]
    render_paths: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)
    render_faces: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)


class FacialListMeshesRequest(BaseModel):
    """turns a picked folder (frontend/src/lib/desktop.js's pickFolderNative
    only ever returns a folder path, never its contents) into the flat,
    non-recursive list of mesh files inside it - the batch's own
    mesh_paths, one file picker/listing step removed from the actual
    batch-processing endpoint below."""

    folder: str


class FacialListMeshesResponse(BaseModel):
    mesh_paths: list[str]


class FacialBatchStartRequest(BaseModel):
    """desktop: real local paths (a folder listing or explicit file picks -
    see frontend/src/lib/desktop.js's pickFolderNative/pickFileNative).
    browser batches are a separate multipart upload endpoint (uploaded
    bytes have no real path to fall back on, same split every other
    upload flow in this app already makes)."""

    template_id: str
    mesh_paths: list[str]
    points: dict[str, LandmarkPoint]
    measurements: list[FacialMeasurementDef]


class FacialBatchFileResult(BaseModel):
    filename: str
    status: Literal["ok", "error"]
    error: str | None = None
    landmark_points: dict[str, LandmarkPoint] = Field(default_factory=dict)
    values: dict[str, float | None] = Field(default_factory=dict)
    value_errors: dict[str, str] = Field(default_factory=dict)
    # see FacialMeasurementPreviewResponse's own docstring - same purely
    # visual overlay geometry, computed fresh per file since it depends on
    # this mesh's own vertex positions.
    render_paths: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)
    render_faces: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)


class FacialBatchResponse(BaseModel):
    batch_id: str
    results: list[FacialBatchFileResult]


class FacialCorrectionRequest(BaseModel):
    batch_id: str
    filename: str
    point_id: str
    point: LandmarkPoint


class FacialCorrectionResponse(BaseModel):
    """only the measurements that reference the corrected point - the
    frontend merges this into its own per-file state rather than
    overwriting everything, so an unrelated measurement's value never
    flickers/recomputes needlessly."""

    landmark_point: LandmarkPoint  # the snapped correction, echoed back
    values: dict[str, float | None]
    value_errors: dict[str, str]
    # same overlay geometry as FacialMeasurementPreviewResponse, only for
    # the affected measurements (same set of ids as `values` above).
    render_paths: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)
    render_faces: dict[str, list[LandmarkPoint]] = Field(default_factory=dict)


# --- Facial Anthropometrics <-> Cohort integration --------------------------


class FacialMeasurementsLoadRequest(BaseModel):
    """cohort_path: the currently-open cohort study's own .xlsx (same path
    the Per-patient sidebar's cohort controls already use). measurement_file_path:
    a Facial Anthropometrics batch export (api/routers/facial.py's
    export_batch) - the "attach custom measurements..." control's own file pick."""

    cohort_path: str
    measurement_file_path: str


class FacialMeasurementsLoadResponse(BaseModel):
    """columns are already formatted "Name (ABBR)" (see
    api/routers/facial.py's _measurement_header) - the Cohort workspace
    merges rows_by_cohort_id straight into its own row view by these exact
    keys, so every existing tab (already generic over column names) treats
    them like any other numeric cohort variable with no code changes.
    unmatched/ambiguous are never silently dropped - the frontend surfaces
    them before committing the merge."""

    columns: list[str]
    rows_by_cohort_id: dict[str, dict[str, str]]
    legend: list[dict[str, str]]
    unmatched: list[str]
    ambiguous: dict[str, list[str]]
