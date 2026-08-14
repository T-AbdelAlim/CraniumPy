"""tests for io.py.

test_strip_uninteresting_vertex_colors_* cover a real bug: some .ply files
carry an explicit but uniform vertex-color array (every vertex literally
[255, 255, 255, 255]) rather than no color data at all. trimesh treats that
as real per-vertex color (visual.kind == "vertex"), which round-trips into
an exported GLB as a COLOR_0 attribute - the frontend then reasonably
renders that mesh through a plain white material instead of its usual
beige fallback, looking flatly grey and inconsistent with every later stage
of the same mesh (repair_mesh drops all visual data before those stages
ever see it). load_mesh now clears a uniform vertex-color visual so the
frontend's own beige default applies everywhere, consistently.
"""

import io

import numpy as np
import trimesh

from craniumpy_core.io import mesh_to_glb, strip_uninteresting_vertex_colors


def test_strip_uninteresting_vertex_colors_clears_uniform_white():
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    mesh.visual.vertex_colors = np.tile([255, 255, 255, 255], (len(mesh.vertices), 1))
    assert mesh.visual.kind == "vertex"

    result = strip_uninteresting_vertex_colors(mesh)
    assert result is mesh  # mutates in place, returns the same object
    assert mesh.visual.kind is None


def test_strip_uninteresting_vertex_colors_preserves_real_per_vertex_color():
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    colors = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
    colors[:, 3] = 255
    colors[:, 0] = np.linspace(0, 255, len(mesh.vertices)).astype(np.uint8)
    mesh.visual.vertex_colors = colors

    strip_uninteresting_vertex_colors(mesh)
    assert mesh.visual.kind == "vertex"
    np.testing.assert_array_equal(mesh.visual.vertex_colors, colors)


def test_strip_uninteresting_vertex_colors_noop_without_vertex_visual():
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    assert mesh.visual.kind is None
    strip_uninteresting_vertex_colors(mesh)
    assert mesh.visual.kind is None


def _vertex_colored_mesh() -> trimesh.Trimesh:
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    colors = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
    colors[:, 3] = 255
    colors[:, 0] = np.linspace(0, 255, len(mesh.vertices)).astype(np.uint8)
    colors[:, 1] = 128
    colors[:, 2] = 64
    mesh.visual.vertex_colors = colors
    return mesh


def test_mesh_to_glb_linearizes_vertex_color():
    # regression test: glTF's COLOR_0 is spec'd as linear, but a scanner's
    # captured vertex color is sRGB-encoded like any photo - without a
    # decode step here, the renderer's own linear->sRGB output encoding
    # would land on top of already-sRGB data and wash colors out (see
    # mesh_to_glb's docstring for the full reasoning).
    mesh = _vertex_colored_mesh()
    original_colors = mesh.visual.vertex_colors.copy()

    glb_bytes = mesh_to_glb(mesh)
    reloaded = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", process=False, force="mesh")

    assert reloaded.visual.kind == "vertex"
    reloaded_colors = reloaded.visual.vertex_colors
    # not a straight pass-through - the correction actually changed the data
    assert not np.array_equal(reloaded_colors[:, :3], original_colors[:, :3])
    # alpha is untouched (only rgb is gamma data)
    np.testing.assert_array_equal(reloaded_colors[:, 3], original_colors[:, 3])
    # sRGB->linear only ever darkens (linear <= srgb for the same input,
    # across the whole [0, 255] range, with 0 and 255 as fixed points) -
    # every channel should move down or stay put, never up
    assert np.all(reloaded_colors[:, :3].astype(int) <= original_colors[:, :3].astype(int))
    assert reloaded_colors[:, :3].min() == 0
    # green channel is uniform (128 everywhere) - after decoding it should
    # still be uniform, just at a different (darker) fixed value
    assert len(np.unique(reloaded_colors[:, 1])) == 1
    assert reloaded_colors[0, 1] < 128


def test_mesh_to_glb_leaves_original_mesh_untouched():
    mesh = _vertex_colored_mesh()
    original_colors = mesh.visual.vertex_colors.copy()

    mesh_to_glb(mesh)

    np.testing.assert_array_equal(mesh.visual.vertex_colors, original_colors)


def test_mesh_to_glb_passes_through_meshes_without_vertex_color():
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10.0)
    assert mesh.visual.kind is None

    glb_bytes = mesh_to_glb(mesh)
    reloaded = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", process=False, force="mesh")
    assert len(reloaded.vertices) == len(mesh.vertices)
