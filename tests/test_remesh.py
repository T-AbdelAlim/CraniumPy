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

test_keep_largest_component_* are regression tests for a real bug found on
a real template file: clipping.py's cranial_clip chains an extra angled
plane clip meant to trim stray rear/neck geometry, and on that particular
head's proportions the plane grazed the actual cranium surface at a
shallow angle instead of passing cleanly through the neck - slicing a mesh
at a near-tangent angle leaves behind a scatter of tiny disconnected
slivers (went from 1 component to 225 by the time all of cranial_clip's
stages ran, checked stage by stage on the actual file). repair can't fix
this - it runs before clip on purpose (see pipeline.harmonize's
docstring). resample happened to hide it as a total accident of how
quadric decimation works, which is exactly why it only became visible
once resample defaulted to off.

test_trim_boundary_slivers_* cover the sibling bug: even where a shallow
graze doesn't fully disconnect debris, it still leaves the *boundary
itself* jagged - a saw-tooth fringe of thin triangles right at the open
edge, visible in the viewer as spikes along the clip line. found on a
real subnasale template where the landmark plane grazes near the chin
(boundary triangle aspect ratio up to 344). trim_boundary_slivers erodes
that fringe back to the next real edge loop.

test_clean_boundary_* cover the sequel bug: on a real scan, the ragged
boundary wasn't just a few extreme slivers near one grazing spot - the
landmark plane ran close to tangent to the head's surface for its *whole*
length, so the fringe was hundreds of perfectly ordinary-shaped triangles
each stepping up/down a couple mm. no aspect-ratio threshold touches an
ordinary triangle, so trim_boundary_slivers alone left the sawtooth
untouched. the fix that seemed obvious - relax the boundary loop toward a
smooth curve - turned out to be actively dangerous on its own:
test_relax_boundary_loops_alone_can_create_new_slivers is a regression
test for that, since a boundary triangle often has two of its three
vertices ON the loop, and moving those two independently (each toward
ITS OWN loop neighbors, with no idea they share a triangle) can collapse
a perfectly normal triangle into something worse than the raw clip left
behind - checked on the real file, boundary max aspect ratio went from
344 (raw) to 1521 after 20 rounds of relaxation with no cleanup between
them, and the 2D silhouette that "proved" it was fixed didn't reveal any
of this since the collapsing triangles are edge-on to that view.
clean_boundary interleaves relaxation with a same-round sliver trim so
the two can't compound.
"""

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from craniumpy_core.io import load_mesh
from craniumpy_core.remesh import (
    _boundary_face_mask,
    _face_aspect_ratios,
    _relax_boundary_loops_once,
    clean_boundary,
    keep_largest_component,
    repair_mesh,
    resample_mesh,
    trim_boundary_slivers,
)

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


def test_keep_largest_component_drops_small_fragments():
    # two spheres far apart - definitely two components, and the second
    # one is tiny relative to the first
    big = trimesh.creation.icosphere(subdivisions=3, radius=50.0)
    small = trimesh.creation.icosphere(subdivisions=1, radius=2.0)
    small.vertices += np.array([500.0, 0.0, 0.0])

    combined = trimesh.Trimesh(
        vertices=np.vstack([big.vertices, small.vertices]),
        faces=np.vstack([big.faces, small.faces + len(big.vertices)]),
        process=False,
    )
    assert len(combined.split(only_watertight=False)) == 2

    kept = keep_largest_component(combined)
    assert len(kept.split(only_watertight=False)) == 1
    assert len(kept.faces) == len(big.faces)


def test_keep_largest_component_noop_on_single_component():
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
    assert len(mesh.split(only_watertight=False)) == 1
    kept = keep_largest_component(mesh)
    assert len(kept.vertices) == len(mesh.vertices)
    assert len(kept.faces) == len(mesh.faces)


def _shallow_angle_clip(radius=50.0, subdivisions=4):
    # cuts a sphere at a plane almost tangent to its own surface - the
    # canonical shallow-graze case: real anatomical scans do this wherever
    # cranial_clip's landmark plane happens to run nearly parallel to the
    # head's local surface (e.g. near the chin).
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    return trimesh.intersections.slice_mesh_plane(
        sphere, plane_normal=[0, 0, 1], plane_origin=[0, 0, radius * 0.99], cap=False
    )


def test_trim_boundary_slivers_drops_jagged_boundary_teeth():
    clipped = _shallow_angle_clip()
    boundary = _boundary_face_mask(clipped)
    ar = _face_aspect_ratios(clipped)
    assert ar[boundary].max() > 5.0  # confirms the setup actually produces slivers

    trimmed = trim_boundary_slivers(clipped, max_aspect_ratio=3.0)
    boundary2 = _boundary_face_mask(trimmed)
    ar2 = _face_aspect_ratios(trimmed)
    assert ar2[boundary2].max() <= 3.0


def test_trim_boundary_slivers_stays_single_component():
    # the same shallow graze that leaves slivers behind also fragments the
    # mesh into many disconnected components (see keep_largest_component's
    # docstring) - trimming has to clean that up too, not just the AR.
    clipped = _shallow_angle_clip()
    assert len(clipped.split(only_watertight=False)) > 1

    trimmed = trim_boundary_slivers(clipped, max_aspect_ratio=3.0)
    assert len(trimmed.split(only_watertight=False)) == 1


def test_trim_boundary_slivers_noop_on_clean_boundary():
    # a clip straight through the middle of the sphere isn't tangent to
    # anything - no slivers to remove, should pass through unchanged.
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=20.0)
    clipped = trimesh.intersections.slice_mesh_plane(
        sphere, plane_normal=[0, 0, 1], plane_origin=[0, 0, 0], cap=False
    )
    trimmed = trim_boundary_slivers(clipped, max_aspect_ratio=3.0)
    assert len(trimmed.faces) == len(clipped.faces)
    assert len(trimmed.vertices) == len(clipped.vertices)


def _near_tangent_single_loop_clip(radius=50.0, subdivisions=5, fraction=0.994):
    # a gentler graze than _shallow_angle_clip - cuts close enough to
    # tangent to leave a clean single boundary loop (not the fragmented
    # debris _shallow_angle_clip produces), which is what clean_boundary
    # actually has to work with in cranial_clip (that fragmentation is
    # keep_largest_component's job, already run before clean_boundary
    # ever sees the mesh).
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    clipped = trimesh.intersections.slice_mesh_plane(
        sphere, plane_normal=[0, 0, 1], plane_origin=[0, 0, radius * fraction], cap=False
    )
    return keep_largest_component(clipped)


def test_relax_boundary_loops_alone_can_create_new_slivers():
    # regression test for the real bug: relaxing the boundary loop toward
    # a smooth curve, with nothing cleaning up after it, can slide two
    # vertices of the same boundary triangle together and collapse it -
    # this is exactly why clean_boundary interleaves relaxation with
    # trimming instead of just calling this in a loop.
    clipped = _near_tangent_single_loop_clip()
    baseline_max_ar = _face_aspect_ratios(clipped)[_boundary_face_mask(clipped)].max()

    relaxed = clipped
    for _ in range(20):
        relaxed = _relax_boundary_loops_once(relaxed, factor=0.5)
    relaxed_max_ar = _face_aspect_ratios(relaxed)[_boundary_face_mask(relaxed)].max()

    assert relaxed_max_ar > baseline_max_ar


def test_clean_boundary_stays_clean_where_relaxation_alone_does_not():
    clipped = _near_tangent_single_loop_clip()

    cleaned = clean_boundary(clipped, rounds=30, max_aspect_ratio=3.0, smooth_factor=0.5)
    boundary = _boundary_face_mask(cleaned)
    ar = _face_aspect_ratios(cleaned)
    assert ar[boundary].max() <= 3.0
    assert len(cleaned.split(only_watertight=False)) == 1


def test_clean_boundary_noop_when_no_open_boundary():
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
    cleaned = clean_boundary(mesh)
    assert len(cleaned.vertices) == len(mesh.vertices)
    assert len(cleaned.faces) == len(mesh.faces)
