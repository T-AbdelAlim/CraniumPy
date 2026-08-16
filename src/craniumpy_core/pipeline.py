"""the actual pipeline: register -> harmonize -> analyze.

glues together registration, clipping, remesh, craniometrics and asymmetry,
same steps as the old gui_methods.py register/cranial_cut/facial_clip/
craniometrics/calculate_asymmetry did, just as plain functions that pass
meshes around in memory - no disk round-tripping between every step, no GUI
code tangled in with the math.

landmarks always come from the user now (sellion, left tragus, right tragus).
I did try automatic detection at one point - deforming a full head template
onto the scan and reading the landmarks back off it - but it took several
minutes with zero feedback on what was happening, and I couldn't find a way
to speed it up without the accuracy falling apart. not worth it, so it's gone.

registration is just the landmark-triangle alignment - that's all
craniometrics actually needs on its own. a non-rigid option (deforming a
template onto the clipped mesh, via registration.nicp) is available as an
alternative to the plain resample in measure_cranial/the facial run
branch - opt-in, since it's real runtime cost for the sole benefit of a
shared topology across a cohort, not something every single-mesh analysis
needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .asymmetry import AsymmetryResult, calculate_asymmetry
from .clipping import clip_plane, cranial_clip, facial_clip, landmark_plane
from .craniometrics import (
    CranioMeasurements,
    FrontalBossingResult,
    extract_measurements,
    find_hc_slice_height,
    frontal_bossing,
    hc_slice_polygon,
    slice_center_of_mass,
)
from .registration.nicp import register_template
from .registration.rigid import RigidTransform, landmark_align, procrustes_fit
from .remesh import RepairMethod, ResampleMethod, clean_boundary, keep_largest_component, repair_mesh, resample_mesh

AnalysisTarget = Literal["cranium", "face"]
ClipMode = Literal["cranial", "facial", "manual"]

ProgressCallback = Callable[[str, str], None]


def _report(on_progress: ProgressCallback | None, stage: str, detail: str = "") -> None:
    if on_progress is not None:
        on_progress(stage, detail)


def _recenter_com_z(mesh: trimesh.Trimesh, landmarks: np.ndarray | None) -> tuple[np.ndarray | None, np.ndarray]:
    """z-only recenter using the landmark-aware CoM slice - shifts
    mesh.vertices in place (same as before), and returns landmarks shifted
    by that same offset (None straight through if there's no landmarks
    array at all - harmonize()'s manual-clip-mode caller doesn't require
    one), since a landmark array is documented to always be "in the same
    frame as" whichever mesh it's paired with (see CranialAnalysisResult's
    own field docs) - without this, sellion (and everything derived from
    it, like frontal_bossing) stays at its pre-recenter position while the
    mesh itself has moved, so the two silently drift apart in Z whenever
    com_translation is on. doesn't mutate the given landmarks array
    itself: measure_cranial can be re-run (a fresh /run without a fresh
    /clip - changing resample settings, fitting a template) against the
    same stored clip_result, so mutating that shared array in place would
    double-apply the offset on a second call.

    also returns the offset itself: measure_cranial has to map points from
    one post-recenter frame into another (see there), which needs both
    frames' own offsets, not just their shifted landmarks."""
    com = slice_center_of_mass(mesh, landmarks=landmarks)
    offset = np.array([0.0, 0.0, com[2]])
    mesh.vertices = mesh.vertices - offset
    return (landmarks - offset if landmarks is not None else None), offset


@dataclass
class RegistrationResult:
    mesh: trimesh.Trimesh
    landmarks: np.ndarray  # (3, 3) [sellion, left_tragus, right_tragus], post-rigid-alignment
    transform: RigidTransform
    # only set for target="face" - the exact vector that branch subtracts to
    # put the sellion at the origin (see register() below), captured before
    # the subtraction. this is what lets metopic.hc_slice_height_facial_frame
    # reconstruct the target="cranium"-equivalent frame from a facial
    # registration without a second register() call - see that function.
    sellion_offset: np.ndarray | None = None


def register(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: AnalysisTarget = "cranium",
    com_translation: bool = True,
    on_progress: ProgressCallback | None = None,
) -> RegistrationResult:
    """rigidly registers the mesh using the 3 landmarks you give it (sellion,
    left_tragus, right_tragus, in the mesh's own coordinates).

    same as the old gui_methods.register, including the two extra
    translations it did beyond the landmark alignment itself: an optional
    Z-only center-of-mass nudge (helps smooth out variance from imprecise
    landmark picking), and for facial targets, re-centering so the sellion
    ends up sitting at the origin.
    """
    landmarks = np.asarray(landmarks, dtype=np.float64)
    if landmarks.shape != (3, 3):
        raise ValueError(f"expected 3 landmarks (sellion, left_tragus, right_tragus), got shape {landmarks.shape}")

    _report(on_progress, "register", "aligning to reference landmarks")
    transform = landmark_align(landmarks)
    registered_mesh = trimesh.Trimesh(
        vertices=transform.apply(np.asarray(mesh.vertices)),
        faces=mesh.faces,
        process=False,
        # rigid transform, doesn't touch UV - keep the texture/visual data
        visual=mesh.visual,
    )
    new_landmarks = transform.apply(landmarks)

    if com_translation:
        _report(on_progress, "register", "center-of-mass correction")
        # decimated proxy so this stays fast on a raw 100k+-vertex scan -
        # nothing downstream needs this precise, harmonize() re-centers
        # again later on the small final mesh anyway
        proxy = resample_mesh(registered_mesh, n_vertices=20_000)
        com = slice_center_of_mass(proxy)
        z_offset = np.array([0.0, 0.0, com[2]])
        registered_mesh.vertices = registered_mesh.vertices - z_offset
        new_landmarks = new_landmarks - z_offset

    sellion_offset = None
    if target == "face":
        sellion_offset = new_landmarks[0].copy()
        registered_mesh.vertices = registered_mesh.vertices - sellion_offset
        new_landmarks = new_landmarks - sellion_offset

    return RegistrationResult(mesh=registered_mesh, landmarks=new_landmarks, transform=transform, sellion_offset=sellion_offset)


def hc_slice_height_facial_frame(reg: RegistrationResult) -> float:
    """the head-circumference slice height, in a target="face" registration's
    own frame - the same height a target="cranium" run on this same patient
    would have found, not an independently-estimated one (see
    craniumpy_core.metopic's module docstring for why that matters).

    reg.sellion_offset (only set for target="face", see register()) is the
    exact vector that branch subtracted to put the sellion at the origin -
    adding it back reconstructs the target="cranium"-equivalent mesh/
    landmarks without a second register() call (rotation and the CoM nudge
    are already identical between the two branches up to that point, see
    register()'s docstring), then find_hc_slice_height runs the same search
    extract_measurements uses for a real cranial run, and the result gets
    shifted back into reg's own frame by subtracting the same offset's Y
    component. cheap either way - this is one vertex-array addition and one
    slice search, not a repair/clip/CoM-proxy-resample redo."""
    if reg.sellion_offset is None:
        raise ValueError("hc_slice_height_facial_frame needs a target=\"face\" registration (reg.sellion_offset is None)")
    cranial_mesh = trimesh.Trimesh(
        vertices=np.asarray(reg.mesh.vertices) + reg.sellion_offset, faces=reg.mesh.faces, process=False
    )
    cranial_landmarks = reg.landmarks + reg.sellion_offset
    cranial_slice_height = find_hc_slice_height(cranial_mesh, cranial_landmarks)
    return cranial_slice_height - reg.sellion_offset[1]


def rough_bounding_clip(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    alt_frontal_landmark: np.ndarray | None = None,
    side_margin: float = 50.0,
    front_margin: float = 50.0,
    bottom_margin: float = 100.0,
) -> trimesh.Trimesh:
    """crops the raw, unrepaired mesh down to a generous area around the
    head before the expensive repair step - repair's runtime scales with
    mesh size, and a full photogrammetry scan can carry a lot of torso,
    background, or hair that has nothing to do with the cranial/facial clip
    that happens afterward, on the repaired result.

    the left/right/front boundary is an ellipse in the horizontal (x, z)
    plane, not a box - a head's actual cross-section is rounded, so a box's
    sharp diagonal corners were always wasted margin nothing anatomical
    ever reached anyway (see _clip_frontal_ellipse). open on 2 sides on
    purpose: nothing bounds the back of the head (no reliable margin exists
    there - occiput shape varies too much to guess a safe cutoff) or the
    top (nothing irrelevant tends to sit there anyway). the other 3 margins
    (left/right, front, bottom - all in mesh units, mm) are generous
    specifically so this rough cut can never end up removing anything the
    real cranial_clip/facial_clip pass would have kept - all it's for is
    throwing away obviously-irrelevant mass before the slow part.
    side_margin extends past whichever of left_tragus/right_tragus is
    further out, front_margin extends past whichever of sellion/
    alt_frontal_landmark sits further forward (can't tell "forward" apart
    for a single point in isolation, so this takes both when given) - the
    ellipse's own x/z reach in each of those individual directions matches
    those margins exactly, same as the box's did; only the diagonal corners
    between them are now rounded off. bottom_margin extends below the same
    landmark plane cranial_clip's own final cut uses (see
    clipping.landmark_plane) - not the flat y=0 you'd get from a naive
    axis-aligned box, so it stays a true margin even on a head registered
    at an angle.

    the ellipse/plane are computed in a fresh, pure landmark-triangle
    registration (same one register() would produce with
    com_translation=False) purely to get a sensible axis-aligned frame to
    work in - the crop is applied back in the mesh's own original frame
    before returning, so callers don't need to care this detour happened.
    """
    landmarks = np.asarray(landmarks, dtype=np.float64)
    transform = landmark_align(landmarks)
    aligned_landmarks = transform.apply(landmarks)
    sellion, left_tragus, right_tragus = aligned_landmarks

    front_z = sellion[2]
    if alt_frontal_landmark is not None:
        aligned_alt = transform.apply(np.asarray(alt_frontal_landmark, dtype=np.float64).reshape(1, 3))[0]
        front_z = max(front_z, aligned_alt[2])

    plane_normal, plane_origin = landmark_plane(aligned_landmarks)

    # an ellipse in the horizontal (x, z) plane, standing in for the 3 flat
    # cuts (left, right, front) a plain box would use - a head's actual
    # cross-section is rounded, not rectangular, so a box's sharp corners
    # were always wasted margin nothing anatomical ever reached anyway;
    # rounding them off trims a bit more irrelevant mass before the slow
    # repair step, without giving up any margin in the direction that
    # matters (see the bound-preserving x_center/x_semi_axis below). left/
    # right stay tied to side_margin past the tragus positions and front to
    # front_margin past sellion/alt_frontal_landmark, exactly as before.
    left_bound = left_tragus[0] + side_margin
    right_bound = right_tragus[0] - side_margin
    x_center = (left_bound + right_bound) / 2.0
    x_semi_axis = abs(left_bound - right_bound) / 2.0
    z_center = plane_origin[2]
    z_semi_axis = max((front_z + front_margin) - z_center, 1.0)

    result = trimesh.Trimesh(vertices=transform.apply(np.asarray(mesh.vertices)), faces=mesh.faces, process=False)
    result = _clip_frontal_ellipse(result, x_center, x_semi_axis, z_center, z_semi_axis)
    result = clip_plane(result, normal=plane_normal, origin=plane_origin - plane_normal * bottom_margin)

    return trimesh.Trimesh(
        vertices=transform.inverse_apply(np.asarray(result.vertices)), faces=result.faces, process=False
    )


def _clip_frontal_ellipse(
    mesh: trimesh.Trimesh, x_center: float, x_semi_axis: float, z_center: float, z_semi_axis: float
) -> trimesh.Trimesh:
    """keeps whole faces inside an ellipse in the x-z (horizontal) plane,
    for z >= z_center - z_semi_axis (the front half) - z below that is left
    completely untouched, same as rough_bounding_clip's own front-only cut
    always was (see its docstring: nothing bounds the back, occiput shape
    varies too much to guess a safe cutoff). a whole-face mask rather than
    a real geometric cut, same reasoning as clipping.clip_sphere: this only
    ever throws away obviously-irrelevant mass before repair, so boundary
    precision doesn't matter here the way it does for the real cranial_clip/
    facial_clip cuts."""
    vertices = np.asarray(mesh.vertices)
    x, z = vertices[:, 0], vertices[:, 2]
    inside_ellipse = ((x - x_center) / x_semi_axis) ** 2 + ((z - z_center) / z_semi_axis) ** 2 <= 1.0
    vertex_kept = (z < z_center - z_semi_axis) | inside_ellipse
    face_indices = np.nonzero(vertex_kept[mesh.faces].all(axis=1))[0]
    if len(face_indices) == 0:
        # mesh.submesh([...], append=True) hands back a bare (empty) list
        # instead of a Trimesh when there's nothing left, rather than an
        # empty mesh - trips up callers that expect a Trimesh back
        # unconditionally (this function's own type, and every caller of
        # it downstream).
        return trimesh.Trimesh(vertices=np.empty((0, 3)), faces=np.empty((0, 3), dtype=np.int64), process=False)
    return mesh.submesh([face_indices], append=True)


def harmonize(
    mesh: trimesh.Trimesh,
    target: AnalysisTarget,
    landmarks: np.ndarray | None = None,
    clip_mode: ClipMode | None = None,
    manual_plane_normal: np.ndarray | None = None,
    manual_plane_origin: np.ndarray | None = None,
    n_vertices: int | None = 10_000,
    repair: bool = True,
    repair_method: RepairMethod = "pymeshfix",
    resample_method: ResampleMethod = "quadric",
    com_translation: bool = True,
    trim_rear_neck: bool = True,
    on_progress: ProgressCallback | None = None,
) -> trimesh.Trimesh:
    """repair -> clip (incl. boundary cleanup) -> resample, on a mesh
    that's already been through register().

    clip_mode defaults to whatever's normal for the target ("cranial" for
    cranium, "facial" for face). pass "manual" with manual_plane_normal /
    manual_plane_origin to clip along your own plane instead (e.g. from the
    interactive widget in the viewer) - keeps the +normal side, same as
    clipping.clip_plane.

    repair runs before clipping, not after: repair fixes real scan defects,
    and the clip boundary is left open on purpose (see clipping.py).
    repairing after clipping caps the open boundary with a flat patch that
    was never supposed to be there.

    boundary cleanup (clean_boundary, baked into cranial_clip/facial_clip,
    and run explicitly below for manual clip_mode) has to happen before
    resampling, not after: quadric decimation isn't boundary-aware and can
    fragment a still-jagged loop into pieces too small to detect as a loop
    at all, which makes any later cleanup a silent no-op - resample only
    ever gets to work with an already-clean boundary this way.

    n_vertices=None skips resampling. repair=False skips repair (matches
    the old facial_clip pipeline, which never repaired at all). see
    clipping.py and remesh.py for what each method actually does.

    trim_rear_neck is cranial-only, passed straight through to
    cranial_clip - set False for anything registered on a landmark other
    than sellion (see cranial_clip's docstring for why).
    """
    if clip_mode is None:
        clip_mode = "cranial" if target == "cranium" else "facial"

    result = mesh
    if repair:
        _report(on_progress, "repair", f"repairing mesh ({repair_method})")
        result = repair_mesh(result, method=repair_method)

    _report(on_progress, "clip", f"clipping ({clip_mode})")
    if clip_mode == "manual":
        if manual_plane_normal is None or manual_plane_origin is None:
            raise ValueError("manual clipping needs manual_plane_normal and manual_plane_origin")
        result = clip_plane(result, normal=manual_plane_normal, origin=manual_plane_origin)
        result = keep_largest_component(result)
        result = clean_boundary(result)
    elif clip_mode == "cranial":
        if landmarks is None:
            raise ValueError("cranial clipping needs the mesh's registered landmarks")
        result = cranial_clip(result, landmarks, trim_rear_neck=trim_rear_neck)
    elif clip_mode == "facial":
        if landmarks is None:
            raise ValueError("facial clipping needs the mesh's registered landmarks")
        result = facial_clip(result, landmarks)
    else:
        raise ValueError(f"unknown clip_mode {clip_mode!r}")

    # every branch above already cleans up after itself now - this is just
    # a cheap no-op safety net (see keep_largest_component's own docstring).
    result = keep_largest_component(result)

    if n_vertices is not None:
        _report(on_progress, "resample", f"resampling to {n_vertices} vertices ({resample_method})")
        result = resample_mesh(result, n_vertices=n_vertices, method=resample_method)

    if com_translation and target == "cranium":
        # landmarks here so the CoM slice skips past ear-level (see
        # slice_center_of_mass/extract_measurements) - the clip keeps the
        # raw landmark plane on purpose, so the ears are still attached.
        #
        # Z (depth) only, same as register()'s own com_translation - this
        # step exists to compensate for imprecise landmark picking along
        # depth, not to re-center the head side to side or vertically. a
        # real left/right CoM offset is often genuine anatomy
        # (plagiocephaly, facial asymmetry) and shouldn't get erased.
        _recenter_com_z(result, landmarks)

    return result


@dataclass
class AnalysisResult:
    mesh: trimesh.Trimesh
    landmarks: np.ndarray
    craniometrics: CranioMeasurements | None
    asymmetry: AsymmetryResult | None


def analyze(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: AnalysisTarget = "cranium",
    com_translation: bool = True,
    clip_mode: ClipMode | None = None,
    manual_plane_normal: np.ndarray | None = None,
    manual_plane_origin: np.ndarray | None = None,
    n_vertices: int | None = 10_000,
    repair: bool = True,
    repair_method: RepairMethod = "pymeshfix",
    resample_method: ResampleMethod = "quadric",
    on_progress: ProgressCallback | None = None,
) -> AnalysisResult:
    """the whole thing: register -> harmonize (clip/repair/resample) -> measure
    (craniometrics for cranium, asymmetry for face)."""
    reg = register(
        mesh,
        landmarks,
        target=target,
        com_translation=com_translation,
        on_progress=on_progress,
    )
    harmonized = harmonize(
        reg.mesh,
        target=target,
        landmarks=reg.landmarks,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        n_vertices=n_vertices,
        repair=repair,
        repair_method=repair_method,
        resample_method=resample_method,
        com_translation=com_translation,
        # tied to com_translation, not hardcoded True - cranial_clip's
        # rear/neck safety plane assumes the pose the CoM nudge produces
        trim_rear_neck=com_translation,
        on_progress=on_progress,
    )

    _report(on_progress, "analyze", "computing measurements")
    # landmarks here for the same reason as harmonize()'s com_translation -
    # the clipped mesh still has the ears attached, so the HC/BPD slice
    # search needs to skip past them itself
    craniometrics_result = extract_measurements(harmonized, landmarks=reg.landmarks) if target == "cranium" else None
    asymmetry_result = calculate_asymmetry(harmonized) if target == "face" else None
    _report(on_progress, "done", "")

    return AnalysisResult(
        mesh=harmonized,
        landmarks=reg.landmarks,
        craniometrics=craniometrics_result,
        asymmetry=asymmetry_result,
    )


def _sellion_com_z_offset(mesh: trimesh.Trimesh, landmarks: np.ndarray) -> float:
    """the center-of-mass Z-nudge register()'s com_translation branch
    computes, in the sellion-tragus-aligned frame - a plain float, not a
    vector, since analyze_cranial needs to reuse this magnitude along
    each frame's own Z axis, not carry a rotated vector between frames.

    exists so the alt-frontal pass can reuse the same correction the
    sellion pass would use, instead of scanning slices in whatever frame
    its own (e.g. subnasale-tragus) triangle produced - "center of mass
    of the head" shouldn't depend on which frontal point you clicked.
    """
    sellion_align = landmark_align(landmarks)
    aligned_mesh = trimesh.Trimesh(
        vertices=sellion_align.apply(np.asarray(mesh.vertices)), faces=mesh.faces, process=False
    )
    proxy = resample_mesh(aligned_mesh, n_vertices=20_000)
    com = slice_center_of_mass(proxy)
    return float(com[2])


@dataclass
class CranialAnalysisResult:
    display_registered_mesh: trimesh.Trimesh  # pre-harmonize, in the display frame - viewer "registered" stage / _rg.ply
    display_mesh: trimesh.Trimesh  # post-harmonize, in the display frame - viewer "result" stage / _rg_{C|F}.ply
    display_landmarks: np.ndarray  # registered landmarks in the SAME frame as display_mesh
    display_hc_polygon: np.ndarray | None  # HC ring, carried into the display frame - see analyze_cranial
    display_bpd_ofd_points: np.ndarray  # (front_opt, occ_opt, lh_opt, rh_opt), carried into the display frame same as display_hc_polygon
    craniometrics: CranioMeasurements  # always computed from the sellion pass
    frontal_bossing: FrontalBossingResult | None  # always computed from the sellion pass too - see frontal_bossing()
    # frontal_bossing carried into the display frame, same treatment as
    # display_hc_polygon/display_bpd_ofd_points above - the angle itself is
    # frame-relative (measured against "horizontal", i.e. the frame's own
    # z-axis), so unlike craniometrics' scalar numbers this one genuinely
    # is a different value depending on which frame is showing, not just a
    # different position for the same number. == frontal_bossing when
    # there's no alt frontal landmark (single frame, nothing to carry).
    display_frontal_bossing: FrontalBossingResult | None
    # cranial asymmetry - same mirror-and-ICP method as facial's, always
    # computed from the sellion pass, same reasoning as craniometrics/
    # frontal_bossing (see measure_cranial).
    asymmetry: AsymmetryResult | None
    # asymmetry carried into the display frame: mean_asymmetry_index is a
    # property of the mesh's own shape, unaffected by rigid pose, so it's
    # copied rather than recomputed (same "carry, don't recompute" reasoning
    # as display_frontal_bossing's angle_deg); the heatmap is per-vertex and
    # sellion_mesh/display_mesh don't share vertex correspondence, so each
    # display_mesh vertex instead borrows its value from the nearest
    # transformed sellion-mesh vertex (see measure_cranial). ==
    # asymmetry when there's no alt frontal landmark.
    display_asymmetry: AsymmetryResult | None
    sellion_mesh: trimesh.Trimesh  # post-harmonize, sellion frame - always this, for the saved 2D figure
    sellion_landmarks: np.ndarray
    sellion_hc_polygon: np.ndarray | None
    used_alt_frontal: bool


@dataclass
class CranialClipResult:
    """everything register_and_clip_cranial produces - repaired, registered,
    and clipped (repair + clip + boundary cleanup), but NOT yet resampled
    or measured. see measure_cranial for the rest."""

    sellion_registered_mesh: trimesh.Trimesh  # pre-clip, sellion frame
    sellion_registered_landmarks: np.ndarray
    display_registered_mesh: trimesh.Trimesh  # pre-clip, display frame (== sellion's when no alt frontal)
    display_registered_landmarks: np.ndarray
    sellion_clipped_mesh: trimesh.Trimesh  # post repair+clip+boundary-cleanup, pre-resample, sellion frame
    display_clipped_mesh: trimesh.Trimesh  # same, display frame
    used_alt_frontal: bool


def register_and_clip_cranial(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    alt_frontal_landmark: np.ndarray | None = None,
    com_translation: bool = True,
    clip_mode: ClipMode | None = None,
    manual_plane_normal: np.ndarray | None = None,
    manual_plane_origin: np.ndarray | None = None,
    on_progress: ProgressCallback | None = None,
) -> CranialClipResult:
    """the "Clip" half of the cranial pipeline: register + repair + clip +
    boundary cleanup, no resample. split out from analyze_cranial (which is
    now a thin wrapper over this + measure_cranial) so a caller iterating on
    a manual clip plane can re-run just this part instead of the whole
    thing - see measure_cranial for the resample+measure half, and
    pipeline.py's module-level docs for why this split exists.

    mesh must already be repaired (repair_mesh) - unlike the old
    monolithic analyze_cranial, repair never happens in here. repair is
    orientation-invariant (merging coincident vertices, filling holes
    doesn't care how the mesh is rotated - verified byte-identical face
    connectivity and vertex positions agreeing to ~1e-14 whether it runs
    before or after a rigid transform), so the caller is expected to
    repair once and reuse that result across repeated calls here instead
    of re-running pymeshfix - the single most expensive step - on every
    plane tweak.

    same sellion-anchoring logic as analyze_cranial's docstring: the
    sellion pass always runs, the alt-frontal pass only if
    alt_frontal_landmark is given, and com_translation's actual magnitude
    is computed once from sellion-tragus (_sellion_com_z_offset) and reused
    along the alt frame's own Z axis rather than rotated in from the
    sellion frame.

    the post-resample CoM recenter harmonize() normally applies is
    deliberately skipped here (com_translation=False on both harmonize()
    calls below) and deferred to measure_cranial, which applies it after
    resampling instead - same order analyze_cranial always used, just
    split across two calls now instead of one. trim_rear_neck stays tied
    to the real com_translation setting either way, since that's about
    the clip geometry itself, not the post-resample recenter.
    """
    com_z = _sellion_com_z_offset(mesh, landmarks) if (alt_frontal_landmark is not None and com_translation) else None

    sellion_reg = register(mesh, landmarks, target="cranium", com_translation=com_translation, on_progress=on_progress)
    sellion_clipped = harmonize(
        sellion_reg.mesh,
        target="cranium",
        landmarks=sellion_reg.landmarks,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        n_vertices=None,
        repair=False,
        com_translation=False,
        trim_rear_neck=com_translation,
        on_progress=on_progress,
    )

    if alt_frontal_landmark is None:
        return CranialClipResult(
            sellion_registered_mesh=sellion_reg.mesh,
            sellion_registered_landmarks=sellion_reg.landmarks,
            display_registered_mesh=sellion_reg.mesh,
            display_registered_landmarks=sellion_reg.landmarks,
            sellion_clipped_mesh=sellion_clipped,
            display_clipped_mesh=sellion_clipped,
            used_alt_frontal=False,
        )

    alt_landmarks = np.array([alt_frontal_landmark, landmarks[1], landmarks[2]], dtype=np.float64)
    # com_translation=False here always - register() never derives its own
    # correction from the subnasale-tragus plane. com_z (if set) gets
    # applied below instead, along the alt frame's own Z axis.
    alt_reg = register(mesh, alt_landmarks, target="cranium", com_translation=False, on_progress=on_progress)
    if com_z is not None:
        z_offset = np.array([0.0, 0.0, com_z])
        alt_reg.mesh.vertices = alt_reg.mesh.vertices - z_offset
        alt_reg.landmarks = alt_reg.landmarks - z_offset
    alt_clipped = harmonize(
        alt_reg.mesh,
        target="cranium",
        landmarks=alt_reg.landmarks,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        n_vertices=None,
        repair=False,
        com_translation=False,
        trim_rear_neck=False,
        on_progress=on_progress,
    )

    return CranialClipResult(
        sellion_registered_mesh=sellion_reg.mesh,
        sellion_registered_landmarks=sellion_reg.landmarks,
        display_registered_mesh=alt_reg.mesh,
        display_registered_landmarks=alt_reg.landmarks,
        sellion_clipped_mesh=sellion_clipped,
        display_clipped_mesh=alt_clipped,
        used_alt_frontal=True,
    )


@dataclass
class NicpTemplateConfig:
    """opts measure_cranial (or the facial run branch) into non-rigid
    template fitting instead of a plain resample - see
    registration.nicp.register_template. template must already be a
    trimesh.Trimesh (resolving a shipped name or a filesystem path is the
    API layer's job, not pipeline's), and already in roughly the same
    frame as the mesh it'll be fit onto (see nicp()'s own docstring -
    that's true here since both sides come out of the same landmark-
    triangle registration)."""

    template: trimesh.Trimesh
    alphas: np.ndarray
    gamma: float = 1.0
    dist_threshold: float = 10.0
    inner_iters: int = 3


def measure_cranial(
    clip_result: CranialClipResult,
    com_translation: bool = True,
    n_vertices: int | None = 10_000,
    resample_method: ResampleMethod = "quadric",
    nicp_config: NicpTemplateConfig | None = None,
    on_progress: ProgressCallback | None = None,
    on_nicp_progress: Callable[[int, int], None] | None = None,
    on_nicp_preview: Callable[[np.ndarray], None] | None = None,
) -> CranialAnalysisResult:
    """the "Run" half of the cranial pipeline: resample + measure, given
    whatever register_and_clip_cranial produced. com_translation here must
    match whatever was passed to register_and_clip_cranial - it only
    controls the post-resample recenter step that function deliberately
    left out, not any clip-affecting decision, so passing a different
    value here than was used for clipping doesn't make sense and isn't
    validated against.

    nicp_config, when given, replaces the plain resample (n_vertices/
    resample_method are ignored) with a non-rigid template fit - applies
    uniformly to both the sellion-frame and (when an alt frontal landmark
    was used) display-frame meshes, same as the plain resample already
    did for both. on_nicp_progress/on_nicp_preview are passed straight
    through to nicp.register_template (see its own docstring) - kept
    separate from the coarse (stage, detail) on_progress above since these
    fire far more often and carry numeric/array payloads instead."""

    def _finish(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        if nicp_config is not None:
            _report(on_progress, "nicp", "fitting template (non-rigid)")
            return register_template(
                nicp_config.template,
                mesh,
                alphas=nicp_config.alphas,
                gamma=nicp_config.gamma,
                dist_threshold=nicp_config.dist_threshold,
                inner_iters=nicp_config.inner_iters,
                on_progress=on_nicp_progress,
                on_preview=on_nicp_preview,
            )
        if n_vertices is not None:
            _report(on_progress, "resample", f"resampling to {n_vertices} vertices ({resample_method})")
            mesh = resample_mesh(mesh, n_vertices=n_vertices, method=resample_method)
        return mesh

    sellion_mesh = _finish(clip_result.sellion_clipped_mesh)
    sellion_landmarks = clip_result.sellion_registered_landmarks
    sellion_recenter = np.zeros(3)
    if com_translation:
        # _recenter_com_z shifts sellion_mesh in place and hands back the
        # landmarks shifted by that same offset - sellion_landmarks (and
        # everything derived from it, like frontal_bossing below) has to
        # stay in the mesh's own frame, not clip_result's original one.
        sellion_landmarks, sellion_recenter = _recenter_com_z(sellion_mesh, sellion_landmarks)

    display_recenter = np.zeros(3)
    if clip_result.used_alt_frontal:
        display_mesh = _finish(clip_result.display_clipped_mesh)
        display_landmarks = clip_result.display_registered_landmarks
        if com_translation:
            display_landmarks, display_recenter = _recenter_com_z(display_mesh, display_landmarks)
    else:
        display_mesh = sellion_mesh
        display_landmarks = sellion_landmarks

    _report(on_progress, "analyze", "computing measurements")
    craniometrics = extract_measurements(sellion_mesh, landmarks=sellion_landmarks)
    # always the sellion pass, same reasoning as craniometrics itself -
    # "how much does the forehead bulge relative to sellion" shouldn't
    # depend on which frontal point got clicked for the display frame.
    # anchored to the same slice_height craniometrics just chose, so the
    # bossing angle's forehead point sits on the same reference plane the
    # HC/OFD/BPD numbers do (see frontal_bossing's own docstring).
    bossing = frontal_bossing(sellion_mesh, sellion_landmarks[0], craniometrics.slice_height)
    sellion_hc_polygon = hc_slice_polygon(sellion_mesh, craniometrics.slice_height)
    sellion_bpd_ofd_points = np.array(
        [craniometrics.front_opt, craniometrics.occ_opt, craniometrics.lh_opt, craniometrics.rh_opt]
    )
    # same mirror-and-ICP method as facial asymmetry, applied to the
    # cranial cap instead of the face - both are already registered onto
    # the same x=0-midline reference frame, so calculate_asymmetry needs
    # nothing target-specific to work here.
    asymmetry = calculate_asymmetry(sellion_mesh)

    if not clip_result.used_alt_frontal:
        _report(on_progress, "done", "")
        return CranialAnalysisResult(
            display_registered_mesh=clip_result.display_registered_mesh,
            display_mesh=display_mesh,
            display_landmarks=display_landmarks,
            display_hc_polygon=sellion_hc_polygon,
            display_bpd_ofd_points=sellion_bpd_ofd_points,
            craniometrics=craniometrics,
            frontal_bossing=bossing,
            display_frontal_bossing=bossing,
            asymmetry=asymmetry,
            display_asymmetry=asymmetry,
            sellion_mesh=sellion_mesh,
            sellion_landmarks=sellion_landmarks,
            sellion_hc_polygon=sellion_hc_polygon,
            used_alt_frontal=False,
        )

    # the rigid transform between the two registrations, fitted on the
    # pre-clip meshes (identical vertex sets in two different frames, so
    # this is exact rather than a fit in any meaningful sense).
    registered_transform = procrustes_fit(
        np.asarray(clip_result.sellion_registered_mesh.vertices), np.asarray(clip_result.display_registered_mesh.vertices)
    )

    def to_display(points: np.ndarray) -> np.ndarray:
        """sellion-frame points -> display-frame points.

        registered_transform maps the PRE-recenter frames onto each other,
        but both meshes have since been recentered along their own depth
        axis by their own independent amounts (see _recenter_com_z above) -
        so a point has to be lifted back out of the sellion recenter,
        rotated across, then dropped into the display recenter. skipping
        that composition offsets everything carried across by the two
        offsets combined, which is tens of millimetres on a real head:
        enough to put the whole bossing construction visibly off the mesh.
        """
        return registered_transform.apply(np.atleast_2d(points) + sellion_recenter) - display_recenter

    # HC polygon and the 4 BPD/OFD optima both need the same treatment: the
    # transform is exact, but sellion_mesh and display_mesh each go through
    # their own independent clip/resample, which doesn't preserve vertex
    # correspondence - so the mapped points can still end up a fraction of
    # a millimetre off the display mesh's actual surface. snapping onto
    # display_mesh's surface guarantees the drawn lines always sit exactly
    # on the mesh being shown. batched into one closest_point call.
    to_transform = (
        np.vstack([sellion_hc_polygon, sellion_bpd_ofd_points]) if sellion_hc_polygon is not None else sellion_bpd_ofd_points
    )
    transformed, _, _ = trimesh.proximity.closest_point(display_mesh, to_display(to_transform))
    if sellion_hc_polygon is not None:
        display_hc_polygon = transformed[: len(sellion_hc_polygon)]
        display_bpd_ofd_points = transformed[len(sellion_hc_polygon) :]
    else:
        display_hc_polygon = None
        display_bpd_ofd_points = transformed

    # frontal bossing is measured once, in the sellion frame, at the same
    # stage and on the same mesh as the head circumference - that value is
    # the reported one for either frame, exactly like every craniometric
    # scalar. what changes for the display frame is only where the
    # construction gets DRAWN: the same rigid mapping as above carries
    # sellion/frontal_point/profile across, and the "horizontal" the angle
    # was measured against comes across as a rotated direction rather than
    # the display frame's own +z (those are two different axes whenever the
    # frontal landmark differs, which is the whole point of the alt frame).
    # so the drawn reference line still lies in the sellion-tragus plane,
    # pointing out from sellion, and the drawn angle still visibly equals
    # the reported one.
    if bossing is not None:
        bossing_points = np.vstack([bossing.sellion[np.newaxis, :], bossing.frontal_point[np.newaxis, :], bossing.profile])
        transformed_bossing, _, _ = trimesh.proximity.closest_point(display_mesh, to_display(bossing_points))
        display_bossing = FrontalBossingResult(
            angle_deg=bossing.angle_deg,
            sellion=transformed_bossing[0],
            frontal_point=transformed_bossing[1],
            profile=transformed_bossing[2:],
            # rotation only - a direction has no position to translate
            horizontal=registered_transform.rotation @ bossing.horizontal,
        )
    else:
        display_bossing = None

    # mean_asymmetry_index is a property of the mesh's own shape (how far
    # each vertex sits from its mirrored counterpart), unaffected by which
    # rigid frame it's viewed in - copied, not recomputed, same reasoning
    # as frontal_bossing.angle_deg above. the heatmap is per-vertex though,
    # and sellion_mesh/display_mesh don't share vertex correspondence (each
    # was independently clipped/resampled) - so instead of transforming
    # sellion_mesh's own heatmap array directly, every display_mesh vertex
    # looks up the value carried by whichever transformed sellion_mesh
    # vertex ends up nearest to it. a nearest-neighbour resample of a
    # scalar field between two meshes describing the same anatomy, not a
    # surface snap - display_mesh's own vertices are already ON its
    # surface, unlike the handful of constructed points above.
    sellion_positions_in_display = to_display(np.asarray(sellion_mesh.vertices))
    nearest = cKDTree(sellion_positions_in_display).query(np.asarray(display_mesh.vertices))[1]
    display_asymmetry = AsymmetryResult(
        heatmap=asymmetry.heatmap[nearest], mean_asymmetry_index=asymmetry.mean_asymmetry_index
    )

    _report(on_progress, "done", "")
    return CranialAnalysisResult(
        display_registered_mesh=clip_result.display_registered_mesh,
        display_mesh=display_mesh,
        display_landmarks=display_landmarks,
        display_hc_polygon=display_hc_polygon,
        display_bpd_ofd_points=display_bpd_ofd_points,
        craniometrics=craniometrics,
        frontal_bossing=bossing,
        display_frontal_bossing=display_bossing,
        asymmetry=asymmetry,
        display_asymmetry=display_asymmetry,
        sellion_mesh=sellion_mesh,
        sellion_landmarks=sellion_landmarks,
        sellion_hc_polygon=sellion_hc_polygon,
        used_alt_frontal=True,
    )


def analyze_cranial(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    alt_frontal_landmark: np.ndarray | None = None,
    com_translation: bool = True,
    clip_mode: ClipMode | None = None,
    manual_plane_normal: np.ndarray | None = None,
    manual_plane_origin: np.ndarray | None = None,
    n_vertices: int | None = 10_000,
    repair: bool = True,
    repair_method: RepairMethod = "pymeshfix",
    resample_method: ResampleMethod = "quadric",
    on_progress: ProgressCallback | None = None,
) -> CranialAnalysisResult:
    """the whole cranial pipeline in one call: repair -> register_and_clip_cranial
    -> measure_cranial. kept for callers that want it all at once (the CLI,
    tests, anything not iterating on the clip plane); the API layer calls
    the two halves separately instead so a bad manual clip can be redone
    without repeating the expensive repair step - see this module's other
    docstrings for the split's rationale.

    see register_and_clip_cranial and measure_cranial for what each half
    actually does - the sellion-anchoring, alt-frontal-landmark, and
    com_translation behavior described there all still apply unchanged
    here, just as two calls instead of one.
    """
    if repair:
        _report(on_progress, "repair", f"repairing mesh ({repair_method})")
        mesh = repair_mesh(mesh, method=repair_method)

    clip_result = register_and_clip_cranial(
        mesh,
        landmarks,
        alt_frontal_landmark=alt_frontal_landmark,
        com_translation=com_translation,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        on_progress=on_progress,
    )
    return measure_cranial(
        clip_result,
        com_translation=com_translation,
        n_vertices=n_vertices,
        resample_method=resample_method,
        on_progress=on_progress,
    )
