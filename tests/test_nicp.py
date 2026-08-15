"""tests for registration/nicp.py.

uses small synthetic icospheres rather than the real shipped templates -
the real ones have enough vertices that a full 20-step alpha schedule is
slow to run in a test suite; a small mesh with a short schedule is enough
to check the two properties that actually matter here (it converges onto
the target's shape, and it never changes the source's own topology).
"""

import numpy as np
import trimesh

from craniumpy_core.registration.nicp import nicp, register_template

FAST_ALPHAS = np.linspace(50, 1, 5)


def _sphere(radius: float = 50.0, subdivisions: int = 2) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


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
