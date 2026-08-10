"""rigid registration - point-to-point ICP (used by the asymmetry mirror step)
plus the landmark-triangle alignment that's the main registration step.

convention everywhere here: transformed = points @ R.T + t, points as (N, 3).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

# --------------------------------------------------------------------------
# point-to-point rigid ICP (Besl & McKay 1992). ported from my meanshape
# repo's asymmetry/nicp/icp.py - just switched from their column-vector
# (3,N) convention to row-vector (N,3) since that's what I'm using
# everywhere else, and swapped sklearn's KDTree for scipy's cKDTree since
# scipy's already a dependency and sklearn would only be here for this.
# --------------------------------------------------------------------------


@dataclass
class RigidTransform:
    rotation: np.ndarray  # (3, 3)
    translation: np.ndarray  # (3,)

    def apply(self, points: np.ndarray) -> np.ndarray:
        return points @ self.rotation.T + self.translation

    def compose(self, other: "RigidTransform") -> "RigidTransform":
        """combine into one transform equivalent to self then other."""
        R = other.rotation @ self.rotation
        t = other.rotation @ self.translation + other.translation
        return RigidTransform(R, t)


def _procrustes(source_pts: np.ndarray, target_pts: np.ndarray) -> RigidTransform:
    """SVD-based Procrustes (Kabsch) for point sets that are already 1:1
    matched. Keeps the reflection fix from the original - plain Procrustes can
    hand you a mirror image instead of a rotation, det(R) < 0 catches that and
    flips it back."""
    u1 = source_pts.mean(axis=0)
    u2 = target_pts.mean(axis=0)
    pp1 = source_pts - u1
    pp2 = target_pts - u2

    W = pp1.T @ pp2
    U, _, Vt = np.linalg.svd(W)
    R = (U @ Vt).T
    if np.linalg.det(R) < 0:
        Vt[2, :] *= -1
        R = (U @ Vt).T
    t = u2 - R @ u1
    return RigidTransform(R, t)


def procrustes_icp(
    source_pts: np.ndarray,
    target_pts: np.ndarray,
    tau: float = 1e-6,
    max_iterations: int = 200,
) -> tuple[RigidTransform, int]:
    """standard ICP loop: find nearest neighbors, solve rigid alignment for that
    match, repeat until it stops improving by more than tau.

    kept the convergence check exactly like the original - it's a SUM of
    distances, not a mean, so despite being called something like RMSE in the
    old code it isn't really one. left it as-is since changing it changes how
    many iterations you get before it stops.

    max_iterations is a safety net I added, the old version was a bare
    `while True`. doesn't change what it converges to, just guarantees it
    actually stops at some point.
    """
    tree = cKDTree(target_pts)
    current = source_pts.copy()
    last_metric = 0.0
    transform = RigidTransform(np.eye(3), np.zeros(3))

    for iteration in range(max_iterations):
        _, idx = tree.query(current)
        neighbors = target_pts[idx]

        transform = _procrustes(source_pts, neighbors)
        current = transform.apply(source_pts)

        metric = float(np.sum(np.linalg.norm(current - neighbors, axis=1)))
        if abs(metric - last_metric) < tau:
            return transform, iteration
        last_metric = metric

    return transform, max_iterations


# --------------------------------------------------------------------------
# the actual landmark-triangle alignment. ported from
# registration/picking.py's CoordinatePicking.reg_to_template in the old
# repo. the old code computed a Rodrigues rotation matrix, decomposed it into
# XYZ euler angles, then reapplied those as three separate pyvista
# rotate_x/y/z calls - which just reconstructs the same matrix again since
# decompose->recompose is a no-op here. so I skip that whole round trip and
# just apply the Rodrigues matrix directly. checked this gives numerically
# identical results to the old decompose/recompose approach, see
# tests/test_rigid.py.
# --------------------------------------------------------------------------

# landmarks[0] = nasion, [1] = left tragus, [2] = right tragus, in whatever
# frame the templates are built in. this triangle's centroid sits right
# around (0, 0, 0) by construction.
REFERENCE_TRIANGLE = np.array([
    [1.00000000e-10, -2.75124192e-01, 5.72706234e+01],
    [6.10000000e+01, 1.37562096e-01, -2.86353117e+01],
    [-6.10000000e+01, 1.37562096e-01, -2.86353117e+01],
])

# pipeline.register() re-centers the mesh an extra step for facial targets,
# after landmark_align, shifting everything so the nasion lands at the
# origin (see the nasion_offset subtraction there) - REFERENCE_TRIANGLE
# itself is never adjusted for that second shift, so anything that needs to
# describe landmark positions in the frame a face-target-registered mesh
# actually ends up in (e.g. clipping a template for the overlay comparison)
# needs this version instead of the raw triangle.
FACE_REFERENCE_TRIANGLE = REFERENCE_TRIANGLE - REFERENCE_TRIANGLE[0]


def _rodrigues_align(v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
    """rotation matrix that takes unit(v1) to unit(v2)."""
    v1_u = v1 / np.linalg.norm(v1)
    v2_u = v2 / np.linalg.norm(v2)

    axis = np.cross(v1_u, v2_u)
    axis_norm = np.linalg.norm(axis)
    cos_angle = np.clip(np.dot(v1_u, v2_u), -1.0, 1.0)

    if axis_norm < 1e-12:
        # v1 and v2 are parallel or opposite, no rotation axis to speak of.
        # +1 means already lined up, -1 means exactly backwards - the old code
        # doesn't handle that case either so not worrying about it here.
        return np.eye(3) if cos_angle > 0 else -np.eye(3)

    axis = axis / axis_norm
    angle = np.arccos(cos_angle)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def _face_normal(triangle: np.ndarray) -> np.ndarray:
    v1 = triangle[1] - triangle[0]
    v2 = triangle[2] - triangle[0]
    n = np.cross(v1, v2)
    return n / np.linalg.norm(n)


def landmark_align(landmarks: np.ndarray, reference_triangle: np.ndarray = REFERENCE_TRIANGLE) -> RigidTransform:
    """lines up a patient's 3 landmarks (nasion, left tragus, right tragus, in
    that order) onto the reference triangle. moves the landmark centroid to
    the reference centroid, then two rotations - first line up the nasion
    vector, then the face normal. same two-step approach the old app used.
    """
    landmarks = np.asarray(landmarks, dtype=np.float64)
    ref_centroid = reference_triangle.mean(axis=0)
    lm_centroid = landmarks.mean(axis=0)

    translation = ref_centroid - lm_centroid
    translated = landmarks + translation

    # step 1: line up the centroid->nasion vector with the template's
    R1 = _rodrigues_align(translated[0] - ref_centroid, reference_triangle[0] - ref_centroid)
    stage1 = translated @ R1.T

    # step 2: line up the face normal too, using where the triangle ended up after step 1
    R2 = _rodrigues_align(_face_normal(stage1), _face_normal(reference_triangle))

    R_total = R2 @ R1
    t_total = R_total @ translation
    return RigidTransform(R_total, t_total)
