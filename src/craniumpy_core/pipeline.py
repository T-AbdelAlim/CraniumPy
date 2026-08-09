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
from .craniometrics import CranioMeasurements, extract_measurements, slice_center_of_mass
from .registration.rigid import RigidTransform, landmark_align
from .remesh import RepairMethod, ResampleMethod, repair_mesh, resample_mesh

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
        vertices=transform.apply(np.asarray(mesh.vertices)), faces=mesh.faces, process=False
    )
    new_landmarks = transform.apply(landmarks)

    if com_translation:
        _report(on_progress, "register", "center-of-mass correction")
        com = slice_center_of_mass(registered_mesh)
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
        result = cranial_clip(result, landmarks)
    elif clip_mode == "facial":
        if landmarks is None:
            raise ValueError("facial clipping needs the mesh's registered landmarks")
        result = facial_clip(result, landmarks)
    else:
        raise ValueError(f"unknown clip_mode {clip_mode!r}")

    if n_vertices is not None:
        _report(on_progress, "resample", f"resampling to {n_vertices} vertices ({resample_method})")
        result = resample_mesh(result, n_vertices=n_vertices, method=resample_method)

    if com_translation and target == "cranium":
        com = slice_center_of_mass(result)
        result.vertices = result.vertices - np.array([com[0], 0.0, com[2]])

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
        on_progress=on_progress,
    )

    _report(on_progress, "analyze", "computing measurements")
    craniometrics_result = extract_measurements(harmonized) if target == "cranium" else None
    asymmetry_result = calculate_asymmetry(harmonized) if target == "face" else None
    _report(on_progress, "done", "")

    return AnalysisResult(
        mesh=harmonized,
        landmarks=reg.landmarks,
        craniometrics=craniometrics_result,
        asymmetry=asymmetry_result,
    )
