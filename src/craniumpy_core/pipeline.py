"""the actual pipeline: register -> harmonize -> analyze.

glues together registration, clipping, remesh, craniometrics and asymmetry,
same steps as the old gui_methods.py register/cranial_cut/facial_clip/
craniometrics/calculate_asymmetry did, just as plain functions that pass
meshes around in memory - no disk round-tripping between every step, no GUI
code tangled in with the math.

landmarks always come from the user now (nasion, left tragus, right tragus).
I did try automatic detection at one point - deforming a full head template
onto the scan and reading the landmarks back off it - but it took several
minutes with zero feedback on what was happening, and I couldn't find a way
to speed it up without the accuracy falling apart. not worth it, so it's gone.

registration is just the landmark-triangle alignment - that's all
craniometrics actually needs. I had a non-rigid mode here too (deforming a
template onto the result for topology-normalized shape comparison) but
pulled it out entirely, not worth the runtime cost for what this app is
actually used for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
import trimesh

from .asymmetry import AsymmetryResult, calculate_asymmetry
from .clipping import clip_plane, cranial_clip, facial_clip
from .craniometrics import CranioMeasurements, extract_measurements, hc_slice_polygon, slice_center_of_mass
from .registration.rigid import RigidTransform, landmark_align, procrustes_fit
from .remesh import RepairMethod, ResampleMethod, keep_largest_component, repair_mesh, resample_mesh

AnalysisTarget = Literal["cranium", "face"]
ClipMode = Literal["cranial", "facial", "manual"]

ProgressCallback = Callable[[str, str], None]


def _report(on_progress: ProgressCallback | None, stage: str, detail: str = "") -> None:
    if on_progress is not None:
        on_progress(stage, detail)


@dataclass
class RegistrationResult:
    mesh: trimesh.Trimesh
    landmarks: np.ndarray  # (3, 3) [nasion, left_tragus, right_tragus], post-rigid-alignment
    transform: RigidTransform


def register(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: AnalysisTarget = "cranium",
    com_translation: bool = True,
    on_progress: ProgressCallback | None = None,
) -> RegistrationResult:
    """rigidly registers the mesh using the 3 landmarks you give it (nasion,
    left_tragus, right_tragus, in the mesh's own coordinates).

    same as the old gui_methods.register, including the two extra
    translations it did beyond the landmark alignment itself: an optional
    Z-only center-of-mass nudge (helps smooth out variance from imprecise
    landmark picking), and for facial targets, re-centering so the nasion
    ends up sitting at the origin.
    """
    landmarks = np.asarray(landmarks, dtype=np.float64)
    if landmarks.shape != (3, 3):
        raise ValueError(f"expected 3 landmarks (nasion, left_tragus, right_tragus), got shape {landmarks.shape}")

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

    if target == "face":
        nasion_offset = new_landmarks[0].copy()
        registered_mesh.vertices = registered_mesh.vertices - nasion_offset
        new_landmarks = new_landmarks - nasion_offset

    return RegistrationResult(mesh=registered_mesh, landmarks=new_landmarks, transform=transform)


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

    boundary cleanup (clean_boundary, baked into cranial_clip/facial_clip)
    has to run before resampling, not after: quadric decimation isn't
    boundary-aware and can fragment a still-jagged loop into pieces too
    small to detect as a loop at all, which makes any later cleanup a
    silent no-op - resample only ever gets to work with an already-clean
    boundary this way. clip_plane's own output (manual clip_mode) was
    never boundary-cleaned.

    n_vertices=None skips resampling. repair=False skips repair (matches
    the old facial_clip pipeline, which never repaired at all). see
    clipping.py and remesh.py for what each method actually does.

    trim_rear_neck is cranial-only, passed straight through to
    cranial_clip - set False for anything registered on a landmark other
    than nasion (see cranial_clip's docstring for why).
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

    # cranial_clip/facial_clip already clean up after themselves - this
    # covers manual clip_mode, a bare clip_plane() call that isn't
    # wrapped by anything else. no-op otherwise.
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
        com = slice_center_of_mass(result, landmarks=landmarks)
        result.vertices = result.vertices - np.array([0.0, 0.0, com[2]])

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


def _nasion_com_z_offset(mesh: trimesh.Trimesh, landmarks: np.ndarray) -> float:
    """the center-of-mass Z-nudge register()'s com_translation branch
    computes, in the nasion-tragus-aligned frame - a plain float, not a
    vector, since analyze_cranial needs to reuse this magnitude along
    each frame's own Z axis, not carry a rotated vector between frames.

    exists so the alt-frontal pass can reuse the same correction the
    nasion pass would use, instead of scanning slices in whatever frame
    its own (e.g. subnasale-tragus) triangle produced - "center of mass
    of the head" shouldn't depend on which frontal point you clicked.
    """
    nasion_align = landmark_align(landmarks)
    aligned_mesh = trimesh.Trimesh(
        vertices=nasion_align.apply(np.asarray(mesh.vertices)), faces=mesh.faces, process=False
    )
    proxy = resample_mesh(aligned_mesh, n_vertices=20_000)
    com = slice_center_of_mass(proxy)
    return float(com[2])


@dataclass
class CranialAnalysisResult:
    display_registered_mesh: trimesh.Trimesh  # pre-harmonize, in the display frame - viewer "registered" stage / _registered.ply
    display_mesh: trimesh.Trimesh  # post-harmonize, in the display frame - viewer "result" stage / _final.ply
    display_landmarks: np.ndarray  # registered landmarks in the SAME frame as display_mesh
    display_hc_polygon: np.ndarray | None  # HC ring, carried into the display frame - see analyze_cranial
    craniometrics: CranioMeasurements  # always computed from the nasion pass
    nasion_mesh: trimesh.Trimesh  # post-harmonize, nasion frame - always this, for the saved 2D figure
    nasion_landmarks: np.ndarray
    nasion_hc_polygon: np.ndarray | None
    used_alt_frontal: bool


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
    """the cranial pipeline, with an optional second frontal landmark (e.g.
    subnasale) that takes over as the registration/clip/display frame for
    everything shown, downloaded, or saved - while the craniometrics
    numbers and the saved 2D figure always come from the nasion pass.

    nasion stays the anchor for those two because the HC circumference
    search and the cranial_clip geometry are both tuned against a
    nasion-based registration. swapping in a different frontal point
    doesn't just move that one landmark - landmark_align still pins all 3
    points to the same reference triangle, so the REST of the head has to
    rotate differently to make that work, dragging the whole mesh into a
    different pose. cranial_clip's rear/neck safety plane and the HC
    slice search both assume the nasion pose specifically, so anything
    else needs its own handling (trim_rear_neck=False for the alt pass,
    see cranial_clip's docstring) rather than trusting nasion-tuned
    geometry blindly.

    the two passes register the same input mesh independently, so
    nasion_reg.mesh and alt_reg.mesh (before harmonize touches either
    one) are still in full 1:1 vertex correspondence - fitting a rigid
    transform between them (procrustes_fit) is what carries the HC ring
    from the nasion frame into the display frame.

    com_translation is nasion-anchored too: _nasion_com_z_offset computes
    the correction's magnitude once, from nasion-tragus. the nasion pass
    is untouched (register() handles its own com_translation as usual);
    the alt pass reuses that same number along its own Z axis after its
    own alignment, never through register()'s independent logic and
    never rotated in from the nasion frame - a vector that's purely Z in
    one frame generally isn't purely Z once viewed through a differently
    rotated one, so rotating it in would leak into the alt frame's left-
    right or vertical axis instead of staying a pure depth correction.

    repair runs once here, on the raw mesh, instead of once per pass
    inside each harmonize() call - repair (merging coincident vertices,
    filling holes) doesn't care about orientation, so repairing the same
    topology twice under two different rotations is wasted work, not two
    different results: verified this gives byte-identical face
    connectivity and vertex positions agreeing to ~1e-14 either way. on a
    dense scan repair is the single most expensive step, so doing it once
    instead of twice roughly halves this function's total cost when
    alt_frontal_landmark is given.
    """
    com_z = _nasion_com_z_offset(mesh, landmarks) if (alt_frontal_landmark is not None and com_translation) else None

    if repair and alt_frontal_landmark is not None:
        _report(on_progress, "repair", f"repairing mesh ({repair_method})")
        mesh = repair_mesh(mesh, method=repair_method)
        repair = False  # already done - both harmonize() calls below skip it

    nasion_reg = register(mesh, landmarks, target="cranium", com_translation=com_translation, on_progress=on_progress)
    nasion_mesh = harmonize(
        nasion_reg.mesh,
        target="cranium",
        landmarks=nasion_reg.landmarks,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        n_vertices=n_vertices,
        repair=repair,
        repair_method=repair_method,
        resample_method=resample_method,
        com_translation=com_translation,
        trim_rear_neck=com_translation,
        on_progress=on_progress,
    )

    _report(on_progress, "analyze", "computing measurements")
    craniometrics = extract_measurements(nasion_mesh, landmarks=nasion_reg.landmarks)
    nasion_hc_polygon = hc_slice_polygon(nasion_mesh, craniometrics.slice_height)

    if alt_frontal_landmark is None:
        _report(on_progress, "done", "")
        return CranialAnalysisResult(
            display_registered_mesh=nasion_reg.mesh,
            display_mesh=nasion_mesh,
            display_landmarks=nasion_reg.landmarks,
            display_hc_polygon=nasion_hc_polygon,
            craniometrics=craniometrics,
            nasion_mesh=nasion_mesh,
            nasion_landmarks=nasion_reg.landmarks,
            nasion_hc_polygon=nasion_hc_polygon,
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
    alt_mesh = harmonize(
        alt_reg.mesh,
        target="cranium",
        landmarks=alt_reg.landmarks,
        clip_mode=clip_mode,
        manual_plane_normal=manual_plane_normal,
        manual_plane_origin=manual_plane_origin,
        n_vertices=n_vertices,
        repair=repair,
        repair_method=repair_method,
        resample_method=resample_method,
        com_translation=com_translation,
        trim_rear_neck=False,
        on_progress=on_progress,
    )

    transform = procrustes_fit(np.asarray(nasion_reg.mesh.vertices), np.asarray(alt_reg.mesh.vertices))
    display_hc_polygon = transform.apply(nasion_hc_polygon) if nasion_hc_polygon is not None else None
    if display_hc_polygon is not None:
        # transform is exact for the pre-harmonize registered meshes, but
        # nasion_mesh and alt_mesh each go through their own independent
        # repair/clip/resample after that, which doesn't preserve vertex
        # correspondence - so the transformed ring can end up a couple mm
        # off the display mesh's actual surface. snapping onto alt_mesh's
        # surface here guarantees the drawn line always sits exactly on
        # the mesh being shown, regardless of how much the two passes'
        # post-processing diverged.
        display_hc_polygon, _, _ = trimesh.proximity.closest_point(alt_mesh, display_hc_polygon)

    _report(on_progress, "done", "")
    return CranialAnalysisResult(
        display_registered_mesh=alt_reg.mesh,
        display_mesh=alt_mesh,
        display_landmarks=alt_reg.landmarks,
        display_hc_polygon=display_hc_polygon,
        craniometrics=craniometrics,
        nasion_mesh=nasion_mesh,
        nasion_landmarks=nasion_reg.landmarks,
        nasion_hc_polygon=nasion_hc_polygon,
        used_alt_frontal=True,
    )
