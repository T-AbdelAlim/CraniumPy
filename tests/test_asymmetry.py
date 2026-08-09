"""tests for asymmetry.py.

a perfectly symmetric mesh (icosphere, symmetric across x=0 just by how
it's built) should score close to zero, and pushing one side out should
clearly raise the score. just checking this behaves sensibly, no need for
a real registered face scan for that.
"""

import numpy as np
import trimesh

from craniumpy_core.asymmetry import calculate_asymmetry, mirror_mesh


def test_mirror_mesh_flips_x_only():
    mesh = trimesh.creation.icosphere(radius=10)
    mirrored = mirror_mesh(mesh)
    np.testing.assert_allclose(mirrored.vertices[:, 0], -mesh.vertices[:, 0])
    np.testing.assert_allclose(mirrored.vertices[:, 1:], mesh.vertices[:, 1:])


def test_symmetric_mesh_has_near_zero_asymmetry():
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=30)
    result = calculate_asymmetry(mesh)
    assert result.mean_asymmetry_index < 0.5
    assert np.abs(result.heatmap).max() < 1.0


def test_asymmetric_mesh_scores_higher_than_symmetric():
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=30)
    symmetric_score = calculate_asymmetry(mesh).mean_asymmetry_index

    v = np.asarray(mesh.vertices).copy()
    left = v[:, 0] < 0
    v[left] *= 1.3  # push the whole left side outward
    lopsided = trimesh.Trimesh(vertices=v, faces=mesh.faces, process=False)
    lopsided_score = calculate_asymmetry(lopsided).mean_asymmetry_index

    assert lopsided_score > symmetric_score + 1.0


def test_heatmap_is_zero_on_left_half_by_construction():
    # heatmap always zeroes the left half (x<0) no matter what half_face
    # is - see asymmetry.py's docstring for the whole "this doesn't match
    # the scalar" story
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=30)
    result = calculate_asymmetry(mesh, half_face="right")
    left_mask = np.asarray(mesh.vertices)[:, 0] < 0
    assert np.all(result.heatmap[left_mask] == 0.0)
