"""non-rigid ICP (Amberg et al. 2007), scipy-only.

deforms a template (source) mesh onto a target mesh while preserving the
template's own topology, so every registered patient ends up with the exact
same vertex count/connectivity as the template - useful for a cohort where
you want point-to-point correspondence across patients, not just a good
individual fit. assumes source and target are already rigidly aligned (see
registration.rigid.register/landmark_align) - this only handles the
non-rigid residual on top of that.

ported from a scipy-only implementation in a sibling project
(MeanShape/src/nicp.py) - this codebase actually had an nicp.py once before
(see pipeline.py's own docstring), using open3d + sksparse.cholmod, which
got pulled out entirely as not worth the dependency weight for what the app
was doing at the time. this version needs neither: the normal-equations
solve below (A^T A) x = A^T b is exactly what CHOLMOD's cholesky_AAt did,
just via scipy.sparse.linalg.spsolve instead of a SuiteSparse binding.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import trimesh
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree

DEFAULT_ALPHAS = np.linspace(200, 1, 20)


def _boundary_vertex_indices(faces: np.ndarray) -> np.ndarray:
    """indices of vertices touching an open-boundary edge (one used by only
    a single face) - the rim of a clipped/cut mesh, as opposed to a real
    closed surface.

    used to keep NICP's correspondence search from treating a source mesh's
    open rim like any other point: see nicp()'s own docstring for why a
    plain whole-mesh nearest-point search pulls that rim somewhere it
    shouldn't."""
    if len(faces) == 0:
        return np.empty(0, dtype=np.int64)
    edges = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    sorted_edges = np.sort(edges, axis=1)
    unique_edges, counts = np.unique(sorted_edges, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    if len(boundary_edges) == 0:
        return np.empty(0, dtype=np.int64)
    return np.unique(boundary_edges.reshape(-1))


def _build_stiffness(faces: np.ndarray, n_verts: int, gamma: float) -> tuple[sparse.csr_matrix, int]:
    """edge incidence matrix M (m x n), kroneckered with diag(1,1,1,gamma) -
    the regularizer that penalizes neighboring vertices' affine transforms
    from drifting apart (stiffness), with gamma weighting the translation
    column's contribution separately from rotation/scale."""
    edges = set()
    for f in faces:
        a, b, c = sorted(f)
        edges.update({(a, b), (a, c), (b, c)})
    edges = np.array(sorted(edges))
    m = len(edges)

    rows = np.repeat(np.arange(m), 2)
    cols = edges.reshape(-1)
    vals = np.tile([-1.0, 1.0], m)
    M = sparse.csr_matrix((vals, (rows, cols)), shape=(m, n_verts))

    G = np.diag([1, 1, 1, gamma])
    return sparse.kron(M, G).tocsr(), m


def _build_data_term(src_v: np.ndarray) -> sparse.csr_matrix:
    """per-vertex 4-wide data matrix D (n x 4n) holding [x y z 1] blocks -
    D @ X (X being the per-vertex affine params) gives the transformed
    vertex positions."""
    n = len(src_v)
    rows = np.repeat(np.arange(n), 4)
    cols = np.arange(n * 4)
    vals = np.concatenate([np.append(src_v[i], 1.0) for i in range(n)])
    return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n * 4))


def nicp(
    source: trimesh.Trimesh,
    target: trimesh.Trimesh,
    alphas: np.ndarray = DEFAULT_ALPHAS,
    gamma: float = 1.0,
    dist_threshold: float = 10.0,
    inner_iters: int = 3,
    verbose: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
    on_preview: Callable[[np.ndarray], None] | None = None,
) -> np.ndarray:
    """deforms source onto target, returning an (n, 3) array of deformed
    source vertices - same length/order as source.vertices, so
    trimesh.Trimesh(vertices=result, faces=source.faces) is always a valid,
    topology-preserving output regardless of what target looked like.

    alphas is a stiffness schedule, high to low (rigid to flexible) -
    each level runs inner_iters correspondence-then-solve passes before
    stepping down to the next, looser one. dist_threshold (mesh units)
    drops correspondences farther than that for the current iteration, so
    a target with missing geometry (a hole, a clipped-away region) doesn't
    drag nearby source vertices toward a wrong match on the far side of
    the gap.

    source's own open-boundary vertices (the rim of a clipped mesh, e.g.
    cranial_clip's landmark-plane cut) search for their correspondence
    against ONLY target's open-boundary vertices, not the whole target -
    every other (interior) source vertex still searches the whole target,
    unchanged. plain whole-mesh nearest-point search has no notion of
    "boundary" at all, so a source rim vertex can easily find its closest
    point sitting on the target's INTERIOR surface just past the rim
    (real, since source and target only share the same cut plane
    approximately - individual head shape still differs there) - close
    enough to stay under dist_threshold, so nothing filters it out, and
    the result is the rim visibly getting pulled up/in off the cut plane
    instead of staying a clean matching cut. restricting boundary-to-
    boundary search fixes that at the source, rather than trying to patch
    it after the fact. falls back to the whole target mesh if either side
    has no open boundary at all (a closed/watertight source or target -
    nothing to restrict).

    on_progress/on_preview, when given, fire once per stiffness level (not
    per inner iteration - keeps the overhead reasonable) with the current
    (step, total_steps) and the current deformed vertex array respectively,
    so a caller can drive a progress bar and/or show the fit converging
    live without waiting for the whole schedule to finish.
    """
    src_v = np.asarray(source.vertices, dtype=np.float64)
    n = len(src_v)

    kron_MG, m = _build_stiffness(source.faces, n, gamma)
    D = _build_data_term(src_v)

    # per-vertex affine params, identity initialization (4 rows - 3x3
    # rotation/scale + a translation row - per vertex, stacked).
    X = np.tile(np.vstack([np.eye(3), [0, 0, 0]]), (n, 1)).astype(np.float64)

    target_v = np.asarray(target.vertices, dtype=np.float64)
    tree = cKDTree(target_v)

    target_boundary_idx = _boundary_vertex_indices(target.faces)
    source_boundary_idx = _boundary_vertex_indices(source.faces)
    is_source_boundary = np.zeros(n, dtype=bool)
    is_source_boundary[source_boundary_idx] = True
    tree_boundary = cKDTree(target_v[target_boundary_idx]) if len(target_boundary_idx) else None
    # nothing to restrict against - every source vertex just searches the
    # whole target, exactly like before this function had any boundary
    # handling at all.
    if tree_boundary is None:
        is_source_boundary[:] = False

    for step, alpha in enumerate(alphas):
        for _ in range(inner_iters):
            transformed = D @ X

            dist = np.empty(n)
            idx = np.empty(n, dtype=np.int64)
            if is_source_boundary.any():
                d_b, i_b = tree_boundary.query(transformed[is_source_boundary])
                dist[is_source_boundary] = d_b
                idx[is_source_boundary] = target_boundary_idx[i_b]
            if (~is_source_boundary).any():
                d_i, i_i = tree.query(transformed[~is_source_boundary])
                dist[~is_source_boundary] = d_i
                idx[~is_source_boundary] = i_i
            matches = target_v[idx]

            w = (dist <= dist_threshold).astype(np.float64)
            W = sparse.diags(w)

            A = sparse.vstack([alpha * kron_MG, W @ D]).tocsr()
            B = np.zeros((4 * m + n, 3))
            B[4 * m :] = w[:, None] * matches

            # normal equations (A^T A) X = A^T B - what CHOLMOD's
            # cholesky_AAt did, here via a plain sparse LU solve instead.
            AtA = (A.T @ A).tocsc()
            AtB = A.T @ B
            X = spsolve(AtA, AtB)
            if X.ndim == 1:
                X = X.reshape(-1, 3)

        if verbose:
            print(f"  stiffness {step + 1}/{len(alphas)} (alpha={alpha:.1f})")
        if on_progress is not None:
            on_progress(step + 1, len(alphas))
        if on_preview is not None:
            on_preview(D @ X)

    return D @ X


def register_template(
    template: trimesh.Trimesh,
    target: trimesh.Trimesh,
    alphas: np.ndarray = DEFAULT_ALPHAS,
    gamma: float = 1.0,
    dist_threshold: float = 10.0,
    inner_iters: int = 3,
    on_progress: Callable[[int, int], None] | None = None,
    on_preview: Callable[[np.ndarray], None] | None = None,
) -> trimesh.Trimesh:
    """nicp() plus wrapping the result back into a Trimesh with the
    template's own faces - the shape every caller actually wants."""
    deformed = nicp(
        template,
        target,
        alphas=alphas,
        gamma=gamma,
        dist_threshold=dist_threshold,
        inner_iters=inner_iters,
        on_progress=on_progress,
        on_preview=on_preview,
    )
    return trimesh.Trimesh(vertices=deformed, faces=template.faces, process=False)
