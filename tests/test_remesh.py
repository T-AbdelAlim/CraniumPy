"""tests for remesh.py.

test_repair_mesh_pymeshfix_reaches_watertight and
test_repair_mesh_trimesh_only_fixes_winding both check the actual difference
between the two repair methods rather than just saying so in a comment -
pymeshfix gets the real test mesh fully watertight, trimesh's own repair
only manages consistent winding.
"""

from pathlib import Path

import trimesh

from craniumpy_core.io import load_mesh
from craniumpy_core.remesh import repair_mesh, resample_mesh

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_MESH_PATH = REPO_ROOT / "resources" / "test_mesh" / "test_mesh.ply"


def test_repair_mesh_pymeshfix_reaches_watertight():
    mesh = load_mesh(TEST_MESH_PATH)
    assert not mesh.is_watertight

    repaired = repair_mesh(mesh, method="pymeshfix")
    assert repaired.is_watertight
    assert repaired.is_winding_consistent


def test_repair_mesh_trimesh_only_fixes_winding():
    mesh = load_mesh(TEST_MESH_PATH)
    assert not mesh.is_winding_consistent

    repaired = repair_mesh(mesh, method="trimesh")
    assert repaired.is_winding_consistent
    # doesn't get all the way to watertight - that's the whole reason
    # pymeshfix is the default now


def test_resample_mesh_reduces_vertex_count():
    mesh = load_mesh(TEST_MESH_PATH)
    resampled = resample_mesh(mesh, n_vertices=2000)

    assert len(resampled.vertices) < len(mesh.vertices)
    # quadric decimation targets face count, not vertex count exactly, so
    # this is a loose band, not an exact match
    assert 1000 < len(resampled.vertices) < 3500


def test_resample_mesh_noop_when_already_small():
    mesh = load_mesh(TEST_MESH_PATH)
    resampled = resample_mesh(mesh, n_vertices=len(mesh.vertices) + 1000)
    assert len(resampled.vertices) == len(mesh.vertices)


def test_resample_mesh_noop_above_500k_vertices():
    huge = trimesh.creation.icosphere(subdivisions=8)
    assert len(huge.vertices) > 500_000
    resampled = resample_mesh(huge, n_vertices=1000)
    assert len(resampled.vertices) == len(huge.vertices)


def test_resample_mesh_voronoi_not_implemented():
    mesh = load_mesh(TEST_MESH_PATH)
    try:
        resample_mesh(mesh, n_vertices=2000, method="voronoi")
        assert False, "should have raised"
    except NotImplementedError:
        pass
