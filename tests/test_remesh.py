"""tests for remesh.py.

test_repair_mesh_pymeshfix_reaches_watertight and
test_repair_mesh_trimesh_only_fixes_winding both check the actual difference
between the two repair methods rather than just saying so in a comment -
pymeshfix gets the real test mesh fully watertight, trimesh's own repair
only manages consistent winding.

test_repair_mesh_reconnects_seam_duplicated_vertices is a regression test
for a real bug: a patient scan (photogrammetry, not the clean shipped
templates) had 18,000+ vertices duplicated at seams between reconstructed
patches, never welded on export. pymeshfix's cleaning keeps only the single
largest connected component and drops the rest - on that scan it kept one
fragment and threw away most of the actual head. repair_mesh merges
coincident vertices before handing off to pymeshfix now, specifically to
avoid this.

test_repair_mesh_reconnects_seam_duplicated_vertices_with_texture is a
regression test for the fix above breaking again the moment register()
started carrying texture through: merge_vertices() treats two coincident
vertices with different UV as different (correct for an intentional UV
seam), so a textured mesh only got about half its duplicate seam vertices
merged, leaving most of the fragmentation - and the original bug - back in
place. repair_mesh drops visual data before merging now, since pymeshfix
can't preserve it through repair anyway.
"""

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

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


def test_repair_mesh_reconnects_seam_duplicated_vertices():
    # build a sphere where the top and bottom halves reference two entirely
    # separate (but geometrically coincident) copies of the vertices - same
    # surface, same shape, but split into two "connected components" at the
    # seam because nothing shares a vertex there. this is exactly what an
    # unwelded photogrammetry export seam looks like topologically.
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=50.0)
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces).copy()

    face_center_z = vertices[faces].mean(axis=1)[:, 2]
    top_half = face_center_z > 0

    duplicated_vertices = np.vstack([vertices, vertices])
    split_faces = faces.copy()
    split_faces[top_half] += len(vertices)

    fragmented = trimesh.Trimesh(vertices=duplicated_vertices, faces=split_faces, process=False)
    assert len(fragmented.split(only_watertight=False)) == 2  # sanity check it's actually fragmented

    repaired = repair_mesh(fragmented, method="pymeshfix")
    # full sphere is 100mm across (radius 50) - if repair only kept one
    # fragment (the bug), this comes out ~50mm instead
    z_span = repaired.bounds[1][2] - repaired.bounds[0][2]
    assert z_span > 90


def test_repair_mesh_reconnects_seam_duplicated_vertices_with_texture():
    # same fragmented-seam setup as above, but with a texture attached (each
    # half gets its own UV, same as a real duplicated-seam export would) -
    # repair still has to reconnect the whole sphere, not just merge the
    # vertices that happen to already share a UV.
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=50.0)
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces).copy()

    face_center_z = vertices[faces].mean(axis=1)[:, 2]
    top_half = face_center_z > 0

    duplicated_vertices = np.vstack([vertices, vertices])
    split_faces = faces.copy()
    split_faces[top_half] += len(vertices)

    fragmented = trimesh.Trimesh(vertices=duplicated_vertices, faces=split_faces, process=False)
    uv = np.random.default_rng(0).random((len(duplicated_vertices), 2))
    material = trimesh.visual.material.SimpleMaterial(image=Image.new("RGB", (4, 4)))
    fragmented.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    repaired = repair_mesh(fragmented, method="pymeshfix")
    z_span = repaired.bounds[1][2] - repaired.bounds[0][2]
    assert z_span > 90


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
