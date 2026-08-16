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

quirk carried over from the old code: the MFAI number defaults to the LEFT
half (half_face='left'), but the heatmap always zeroes out the LEFT half, so
only the RIGHT half is visible. the number and the picture describe
different sides of the face by default - kept as-is rather than guessing at
a "fix", but worth knowing before trusting either one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from .registration.rigid import procrustes_icp
from .remesh import resample_mesh

# ICP's convergence check (see registration.rigid.procrustes_icp) is a tight
# ABSOLUTE tolerance on a distance SUM, not a per-point average - so on a
# real (non-perfectly-symmetric) head/face with many thousands of vertices,
# that sum rarely settles by less than the tolerance between iterations, and
# ICP ends up running all the way to its max_iterations safety cap every
# time, each pass repeating a full nearest-neighbor query over every vertex.
# fitting on a decimated proxy instead - the same "proxy so this stays fast
# on a raw 100k+-vertex scan" pattern pipeline.register()'s CoM correction
# already uses - fixes both sides of that: each pass is cheaper AND the
# (now much smaller) sum crosses the same absolute tolerance in far fewer
# iterations. only the RIGID TRANSFORM comes from the proxies; the actual
# heatmap below still gets a real nearest-surface-point query per vertex of
# the full mesh, so per-vertex output resolution is unaffected.
_ICP_PROXY_VERTICES = 8_000


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

    mesh_proxy = resample_mesh(mesh, n_vertices=_ICP_PROXY_VERTICES)
    mirrored_proxy = resample_mesh(mirrored, n_vertices=_ICP_PROXY_VERTICES)
    transform, _ = procrustes_icp(np.asarray(mirrored_proxy.vertices), np.asarray(mesh_proxy.vertices))
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
