"""facial asymmetry / mean facial asymmetry index (MFAI).

ported from gui_methods.py's mirror_mesh/compute_asymmetry_heatmap/
calculate_sum/calculate_asymmetry, old repo. swapped out menpo3d's
VTKClosestPointLocator for trimesh.proximity.closest_point - does the same
thing (real closest point on the surface, not just nearest vertex) and drops
the whole menpo/menpo3d/mayavi/traits dependency chain, which was a lot of
weight for one function call. also reusing registration.rigid.procrustes_icp
for the mirror alignment instead of keeping a second copy of the same ICP
code around (the old nicp/icp.py IterativeClosestPoint stuff is the exact
same algorithm, already ported over there).

needs a mesh that's already been through facial registration (see
registration.rigid.landmark_align with the face centering applied).

found something weird while porting this: the old code computes the MFAI
number from the LEFT half of the face (calculate_sum defaults to
half_face='left' and calculate_asymmetry never overrides it) but then zeroes
out the LEFT half of the heatmap, so only the RIGHT half actually shows up
visually. meaning by default, the heatmap you see and the number you get
are describing two different sides of the face. left this exactly as it
was rather than quietly "fixing" it - it might be intentional for all I
know, but it's worth knowing about before trusting either one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from .registration.rigid import procrustes_icp


@dataclass
class AsymmetryResult:
    heatmap: np.ndarray  # per-vertex signed distance (mm), zeroed on the left half - see module docstring
    mean_asymmetry_index: float  # computed from the left half - see module docstring


def mirror_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """flips the mesh across the sagittal (x=0) plane."""
    mirrored = mesh.copy()
    mirrored.vertices = mirrored.vertices * np.array([-1.0, 1.0, 1.0])
    return mirrored


def _half_mask(points: np.ndarray, half: str) -> np.ndarray:
    assert half in ("left", "right"), "half must be 'left' or 'right'"
    return points[:, 0] < 0 if half == "left" else points[:, 0] > 0


def calculate_asymmetry(mesh: trimesh.Trimesh, half_face: str = "left") -> AsymmetryResult:
    """mirrors the mesh, ICP-aligns the mirror back onto the original, then for
    each original vertex compares its distance from center to the closest
    point on the aligned mirror. gives back both a full heatmap and a single
    number (see module docstring for which half each one is actually showing).
    """
    mirrored = mirror_mesh(mesh)

    transform, _ = procrustes_icp(np.asarray(mirrored.vertices), np.asarray(mesh.vertices))
    aligned_vertices = transform.apply(np.asarray(mirrored.vertices))
    aligned_mirror = trimesh.Trimesh(vertices=aligned_vertices, faces=mirrored.faces, process=False)

    original_points = np.asarray(mesh.vertices)
    closest_points, _, _ = trimesh.proximity.closest_point(aligned_mirror, original_points)

    center = original_points.mean(axis=0)
    center = np.array([center[0], 0.0, center[2]])
    distance_original = np.linalg.norm(original_points - center, axis=1)
    distance_mirror = np.linalg.norm(closest_points - center, axis=1)

    heatmap = distance_original - distance_mirror
    heatmap[_half_mask(original_points, "left")] = 0.0

    mfai_mask = _half_mask(original_points, half_face)
    point_distances = np.linalg.norm(original_points[mfai_mask] - closest_points[mfai_mask], axis=1)
    mfai = float(np.sum(point_distances) / mfai_mask.sum())

    return AsymmetryResult(heatmap=heatmap, mean_asymmetry_index=mfai)
