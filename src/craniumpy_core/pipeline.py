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
        # a rigid transform doesn't touch UV coordinates at all, so there's
        # no reason to drop the texture here - without this, register() was
        # rebuilding the mesh bare (vertices+faces only) and silently
        # throwing away visual/UV/material every time, before repair or
        # clipping ever got a chance to touch it.
        visual=mesh.visual,
    )
    new_landmarks = transform.apply(landmarks)

    if com_translation:
        _report(on_progress, "register", "center-of-mass correction")
        # slice_center_of_mass runs the full craniometrics slice-scan
        # internally (extract_measurements) just to find a rough Z-offset -
        # on a raw, high-poly scan (100k+ vertices, real patient photogrammetry
        # rather than the clean shipped templates) that's genuinely slow, 10+
        # seconds on its own. doing it on a decimated proxy instead of the
        # full mesh cuts that by roughly 8x with no effect on the final
        # reported measurements: nothing downstream trusts this value beyond
        # "roughly centered" - harmonize() does its own precise re-centering
        # later anyway, on the much smaller final mesh, independent of
        # whatever happens here.
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
    """repair -> clip -> resample, on a mesh that's already been through register().

    clip_mode defaults to whatever's normal for the target ("cranial" for
    cranium, "facial" for face). pass "manual" with manual_plane_normal /
    manual_plane_origin to clip along your own plane instead (e.g. from the
    interactive widget in the viewer) - keeps the +normal side, same as
    clipping.clip_plane.

    repair runs BEFORE clipping, not after - repair fixes real defects in the
    scan, and clipping is left open on purpose (see clipping.py). doing it the
    other way around, like this used to, meant repair "fixed" the hole that
    clipping had just cut, capping off the cranium's bottom or the face's back
    with a flat patch that was never supposed to be there.

    n_vertices=None skips resampling. repair=False skips repair (this
    matches what the old facial_clip pipeline did - it never repaired at
    all). see clipping.py and remesh.py for what each method is actually
    doing under the hood.

    trim_rear_neck is cranial-only and passed straight through to
    cranial_clip - set False for anything registered on a landmark other
    than nasion (see cranial_clip's docstring for why that plane can't be
    trusted outside the frame it was tuned against).
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

    # cranial_clip/facial_clip already clean up after themselves (see
    # clipping.py) - this is for the manual clip_mode, a single clip_plane()
    # call that isn't wrapped by anything, but can in principle graze the
    # surface and fragment it the same way. no-op the rest of the time.
    result = keep_largest_component(result)

    if n_vertices is not None:
        _report(on_progress, "resample", f"resampling to {n_vertices} vertices ({resample_method})")
        result = resample_mesh(result, n_vertices=n_vertices, method=resample_method)

    if com_translation and target == "cranium":
        # landmarks here so the CoM slice itself skips past ear-level (see
        # slice_center_of_mass/extract_measurements's landmarks param) -
        # cranial_clip keeps the raw landmark-plane boundary on purpose
        # (the ears stay attached to the clipped mesh), so this mesh can
        # still have them.
        #
        # Z (depth) only - same axis register()'s own com_translation step
        # corrects, on purpose. this used to also subtract com[0] (X, left-
        # right), which was wrong: com_translation is there to compensate
        # for how far forward/back imprecise landmark picking left the head
        # sitting, not to re-center it side to side or vertically (Y was
        # already never touched) - a real leftward or rightward CoM offset
        # is often genuine anatomy (plagiocephaly, facial asymmetry), not
        # something to silently erase by nudging the whole mesh sideways.
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
        # trim_rear_neck tied to com_translation, not just hardcoded True -
        # see clipping.cranial_clip's docstring: that safety plane assumes a
        # pose register()'s CoM nudge is what actually produces, and turning
        # the nudge off drags real cranium into its path.
        trim_rear_neck=com_translation,
        on_progress=on_progress,
    )

    _report(on_progress, "analyze", "computing measurements")
    # landmarks here for the same reason as harmonize()'s com_translation
    # step - the clipped mesh still has the ears attached, so the HC/BPD
    # slice search needs to skip past them itself.
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
    """the same center-of-mass Z-nudge register()'s com_translation branch
    computes (see its docstring) - a rough Z-offset from a decimated proxy's
    slice scan, in the nasion-tragus-aligned frame.

    exists so analyze_cranial's alt-frontal pass can reuse the SAME
    magnitude the nasion pass would use, instead of computing its own:
    calling register()'s independent com_translation logic separately for
    the alt pass scans slices in whatever frame THAT pass's own landmark
    triangle produced, and subnasale-tragus defines a genuinely different
    (more forward-tilted) plane than nasion-tragus does. "center of mass of
    the head" isn't supposed to depend on which frontal point you happened
    to click.

    deliberately returns a bare float (not a raw-mesh-space vector) - see
    analyze_cranial's docstring for why an earlier version of this that
    rotated the offset into raw space, so it could be applied once before
    either landmark triangle got aligned, was wrong: the same physical
    vector decomposes differently into X/Y/Z depending which frame you
    view it through, so "purely Z in the nasion frame" became a mix of
    all three axes once rotated into the alt frame - visibly, the alt
    display mesh floated up/sideways relative to a nasion-plane reference
    instead of sitting flat like the nasion frame does. applying this
    SAME NUMBER along each frame's own Z axis separately (never rotating
    it) is what actually keeps X and Y untouched in both frames, same
    convention as harmonize()'s own com_translation step."""
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
    everything shown, downloaded, or saved - while the craniometrics numbers
    and the saved 2D figure always come from the nasion pass, unconditionally.

    nasion has to stay the anchor for those two specifically, not just be one
    option among several: the HC circumference search (extract_measurements)
    and the whole cranial_clip geometry were both tuned and validated against
    a nasion-based registration. substituting a different point there doesn't
    just move the frontal landmark - it changes which rotation the REST of
    the mesh needs to land the (still 3-point) triangle on the same reference
    triangle, which silently drags the whole head into a different pose. on
    a real file, that pose change was enough to make cranial_clip's fixed
    rear/neck safety plane gouge straight into the actual occiput instead of
    cutting cleanly through the neck - not debris this time (keep_largest_
    component's job), a genuine notch carved into the kept cranium, since
    the surface dents inward without ever fully disconnecting. that's why
    the alt pass below calls harmonize with trim_rear_neck=False - see
    clipping.cranial_clip's docstring for the full story. separately, using
    something other than nasion also made the HC slice search land at ear
    level instead of above it. both of those are exactly why nasion has to
    be mandatory and untouchable for the actual measurement, with anything
    else opt-in and downstream of it.

    the two passes register the exact same input mesh independently, so
    nasion_reg.mesh and alt_reg.mesh (before harmonize's repair/clip/resample
    touches either one) are still in full 1:1 vertex correspondence -
    fitting a rigid transform between them (procrustes_fit) is what actually
    carries the HC ring from the nasion frame into the display frame
    correctly, without having to reason analytically about each pass's own
    separate com_translation offset.

    com_translation is nasion-anchored too, same reasoning: register()'s own
    com_translation logic scans horizontal slices in whatever frame ITS
    landmark triangle produced, so calling it independently for the alt pass
    would measure "center of mass" against the subnasale-tragus plane
    instead of the anatomically standard nasion-tragus one - a genuinely
    different, more forward-tilted cut. _nasion_com_z_offset computes that
    correction's MAGNITUDE once, from nasion-tragus - the nasion pass below
    is otherwise untouched (register() handles its own com_translation
    exactly like it always has), and the alt pass reuses that same number,
    applied along its OWN Z axis after its OWN alignment (never routed
    through register()'s independent com_translation, and never rotated
    into raw mesh space first - see _nasion_com_z_offset's docstring for why
    that's the part that actually matters: the same physical shift, viewed
    through two differently-rotated frames, doesn't decompose into the same
    X/Y/Z split in both, so "purely Z" in one frame can leak into the
    other's left-right or vertical axis if you're not careful about which
    frame you apply it in)."""
    com_z = _nasion_com_z_offset(mesh, landmarks) if (alt_frontal_landmark is not None and com_translation) else None

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
        # see clipping.cranial_clip's docstring - trim_rear_neck=False for
        # the alt pass below isn't the only case that needs it off; turning
        # com_translation off drags the SAME plane into real cranium even
        # in the nasion frame.
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
    # com_translation=False here always - never let register() derive its
    # own independent correction from the subnasale-tragus plane. when
    # com_z is set (com_translation was on), it gets applied right below,
    # along the alt frame's own Z axis specifically - not routed through
    # register() and not rotated in from another frame (see this function's
    # docstring / _nasion_com_z_offset's for why that distinction matters).
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
        # transform is exact for the raw registered meshes (same points,
        # differently posed - see the class docstring), but nasion_mesh and
        # alt_mesh have each been through their own independent repair/clip/
        # resample after that, which doesn't preserve correspondence. on a
        # real scan (subnasale template) that was enough for the ring to
        # land a couple mm off the display mesh's actual surface, worse
        # near the boundary where clean_boundary does the most local
        # reshaping - visibly a gap in the viewer even though the anatomy
        # underneath is right. snapping onto alt_mesh's own surface here
        # guarantees the drawn line is always exactly where the mesh being
        # shown actually is, regardless of how much the two passes'
        # post-processing happened to diverge.
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
