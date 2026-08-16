"""tests for registration/nicp.py.

uses small synthetic icospheres rather than the real shipped templates -
the real ones have enough vertices that a full 20-step alpha schedule is
slow to run in a test suite; a small mesh with a short schedule is enough
to check the two properties that actually matter here (it converges onto
the target's shape, and it never changes the source's own topology).
"""

import numpy as np
import trimesh

from craniumpy_core.registration.nicp import _boundary_vertex_indices, nicp, register_template

FAST_ALPHAS = np.linspace(50, 1, 5)


def _sphere(radius: float = 50.0, subdivisions: int = 2) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


def _grid_mesh(n: int = 5, spacing: float = 10.0, z: float = 0.0) -> trimesh.Trimesh:
    """a flat n x n triangulated grid, open on all four sides - like a
    cranial/facial clip's own open boundary, just simple enough to reason
    about exactly which vertices are on the rim and which aren't."""
    xs = np.arange(n) * spacing
    ys = np.arange(n) * spacing
    xx, yy = np.meshgrid(xs, ys)
    verts = np.column_stack([xx.ravel(), yy.ravel(), np.full(n * n, z)])
    faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1
            faces.append([a, b, c])
            faces.append([b, d, c])
    return trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)


def test_nicp_converges_onto_a_scaled_target():
    # template and target share the same underlying shape (a sphere), just
    # at different scales - correspondence should be near-perfect, so the
    # deformed template should end up close to the target's actual surface,
    # not just somewhere in its rough vicinity.
    source = _sphere(radius=50.0)
    target = _sphere(radius=60.0)

    deformed = nicp(source, target, alphas=FAST_ALPHAS, inner_iters=2, dist_threshold=30.0)

    distances = np.linalg.norm(deformed, axis=1)
    np.testing.assert_allclose(distances, 60.0, atol=2.0)


def test_nicp_recovers_a_local_bump():
    # a smooth local dent/bump, not just a uniform scale - checks the
    # stiffness term actually lets the mesh deform non-rigidly rather than
    # only ever finding a global affine fit.
    source = _sphere(radius=50.0)
    target = _sphere(radius=50.0)
    bump = target.vertices[:, 2] > 40.0
    target.vertices[bump] *= 1.3

    deformed = nicp(source, target, alphas=FAST_ALPHAS, inner_iters=2, dist_threshold=30.0)

    closest, dist, _ = target.nearest.on_surface(deformed)
    assert dist.mean() < 1.5


def test_register_template_preserves_source_topology():
    # output has to keep the template's own vertex count/face connectivity
    # regardless of what the target looks like - that shared topology
    # across every registered patient is the entire point of using this
    # instead of a plain resample.
    source = _sphere(radius=50.0, subdivisions=1)
    target = trimesh.creation.box(extents=[80, 80, 80])

    result = register_template(source, target, alphas=FAST_ALPHAS, inner_iters=1, dist_threshold=100.0)

    assert len(result.vertices) == len(source.vertices)
    np.testing.assert_array_equal(result.faces, source.faces)


def test_nicp_reports_progress_once_per_stiffness_level():
    source = _sphere(radius=50.0)
    target = _sphere(radius=60.0)
    calls = []

    nicp(source, target, alphas=FAST_ALPHAS, inner_iters=2, dist_threshold=30.0, on_progress=lambda step, total: calls.append((step, total)))

    assert calls == [(i + 1, len(FAST_ALPHAS)) for i in range(len(FAST_ALPHAS))]


def test_nicp_preview_matches_source_shape_and_improves_over_time():
    source = _sphere(radius=50.0)
    target = _sphere(radius=60.0)
    previews = []

    nicp(source, target, alphas=FAST_ALPHAS, inner_iters=2, dist_threshold=30.0, on_preview=lambda vertices: previews.append(vertices))

    assert len(previews) == len(FAST_ALPHAS)
    for vertices in previews:
        assert vertices.shape == source.vertices.shape

    # each preview should be at least as close to the target radius as the
    # untouched source was - not a strict per-step monotonic guarantee, but
    # the fit shouldn't be moving backwards by the end of the schedule.
    source_error = abs(np.linalg.norm(source.vertices, axis=1).mean() - 60.0)
    final_error = abs(np.linalg.norm(previews[-1], axis=1).mean() - 60.0)
    assert final_error < source_error


def test_register_template_passes_progress_and_preview_through():
    source = _sphere(radius=50.0, subdivisions=1)
    target = trimesh.creation.box(extents=[80, 80, 80])
    progress_calls = []
    preview_calls = []

    register_template(
        source,
        target,
        alphas=FAST_ALPHAS,
        inner_iters=1,
        dist_threshold=100.0,
        on_progress=lambda step, total: progress_calls.append((step, total)),
        on_preview=lambda vertices: preview_calls.append(vertices),
    )

    assert len(progress_calls) == len(FAST_ALPHAS)
    assert len(preview_calls) == len(FAST_ALPHAS)
    assert preview_calls[-1].shape == source.vertices.shape


def test_boundary_vertex_indices_finds_exactly_the_grid_rim():
    n = 5
    mesh = _grid_mesh(n=n)
    boundary = set(_boundary_vertex_indices(mesh.faces).tolist())

    expected_interior = {(i * n + j) for i in range(1, n - 1) for j in range(1, n - 1)}
    expected_boundary = set(range(n * n)) - expected_interior

    assert boundary == expected_boundary


def test_boundary_vertex_indices_empty_for_a_closed_mesh():
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    assert len(_boundary_vertex_indices(mesh.faces)) == 0


def test_nicp_boundary_vertices_match_only_target_boundary_not_a_closer_interior_point():
    # a naive whole-mesh nearest-point search has no notion of "boundary" -
    # a source rim vertex can match whatever target point is closest in 3D,
    # interior or not. proves the fix by rigging the game as hard as
    # possible: target's own (genuinely interior, still fully surrounded by
    # faces on every side) center vertex gets relocated to sit exactly on
    # top of source's corner - distance zero, the closest any point could
    # ever be. a plain nearest-point search would grab it immediately and
    # never let go; boundary-restricted search can't reach it at all, since
    # relocating a vertex doesn't change its topology.
    n = 5
    source = _grid_mesh(n=n, spacing=10.0, z=0.0)
    target = _grid_mesh(n=n, spacing=10.0, z=5.0)
    center_idx = (n // 2) * n + (n // 2)
    target.vertices[center_idx] = source.vertices[0].copy()

    deformed = nicp(source, target, alphas=np.array([1.0]), inner_iters=3, dist_threshold=100.0)

    true_corner = target.vertices[0]  # (0, 0, 5) - source corner's real counterpart
    trap = target.vertices[center_idx]  # (0, 0, 0) - the relocated interior vertex

    dist_to_truth = np.linalg.norm(deformed[0] - true_corner)
    dist_to_trap = np.linalg.norm(deformed[0] - trap)
    assert dist_to_truth < dist_to_trap
