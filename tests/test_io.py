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

import numpy as np
import trimesh

from craniumpy_core.io import strip_uninteresting_vertex_colors


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
