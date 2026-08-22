"""unit tests for src/craniumpy_core/facial_measurements.py - pure geometry,
no FastAPI needed, same style as test_cohort.py. router-level plumbing
(api/routers/facial.py) is covered separately in test_facial_api.py."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from craniumpy_core.facial_measurements import (
    angle_degrees,
    build_area_boundary,
    build_topology,
    compute_measurement,
    enclosed_area,
    geodesic_distance,
    geodesic_path_vertices,
    nearest_vertex_index,
    straight_distance,
)

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "src" / "craniumpy_core" / "templates" / "template_face.ply"


def _grid_mesh(nx: int, ny: int, spacing: float = 1.0) -> trimesh.Trimesh:
    """a flat nx*ny grid in the z=0 plane, each unit cell split into 2
    triangles - lets area/distance expectations be computed by hand exactly
    (every cell has area spacing**2, every grid-line hop has length spacing)."""
    xs, ys = np.meshgrid(np.arange(nx) * spacing, np.arange(ny) * spacing, indexing="xy")
    vertices = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(nx * ny)])
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            v00 = j * nx + i
            v10 = j * nx + (i + 1)
            v01 = (j + 1) * nx + i
            v11 = (j + 1) * nx + (i + 1)
            faces.append([v00, v10, v11])
            faces.append([v00, v11, v01])
    return trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=False)


def _vertex_index(nx: int, i: int, j: int) -> int:
    return j * nx + i


# --- nearest_vertex_index --------------------------------------------------


def test_nearest_vertex_index_snaps_to_the_closest_vertex():
    mesh = _grid_mesh(3, 3)
    idx = nearest_vertex_index(mesh, [1.1, 0.9, 0.4])
    assert idx == _vertex_index(3, 1, 1)


# --- straight_distance / angle_degrees -------------------------------------


def test_straight_distance_matches_hand_computed_value():
    mesh = _grid_mesh(3, 3)
    d = straight_distance(mesh, _vertex_index(3, 0, 0), _vertex_index(3, 2, 0))
    assert d == pytest.approx(2.0)


def test_angle_degrees_right_angle():
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array([[0, 1, 2]]), process=False)
    assert angle_degrees(mesh, 1, 0, 2) == pytest.approx(90.0)


def test_angle_degrees_straight_line_is_180():
    vertices = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array([[0, 1, 2]]), process=False)
    assert angle_degrees(mesh, 0, 1, 2) == pytest.approx(180.0)


def test_angle_degrees_rejects_coincident_points():
    vertices = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array([[0, 1, 2]]), process=False)
    with pytest.raises(ValueError, match="coincide"):
        angle_degrees(mesh, 0, 1, 2)


# --- geodesic_distance / geodesic_path_vertices -----------------------------


def test_geodesic_distance_between_directly_connected_vertices_equals_the_edge_length():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    d = geodesic_distance(mesh, topology, _vertex_index(3, 0, 0), _vertex_index(3, 1, 0))
    assert d == pytest.approx(1.0)


def test_geodesic_distance_along_a_straight_grid_line_matches_straight_distance():
    # a straight run along a grid axis has a mesh edge at every step, so the
    # shortest surface path exactly equals the straight-line distance - a
    # clean exact-match case distinct from the "detour" inequality below.
    mesh = _grid_mesh(4, 4)
    topology = build_topology(mesh)
    a, b = _vertex_index(4, 0, 0), _vertex_index(4, 3, 0)
    assert geodesic_distance(mesh, topology, a, b) == pytest.approx(straight_distance(mesh, a, b))


def test_geodesic_distance_is_never_shorter_than_straight_distance_on_a_real_curved_mesh():
    mesh = trimesh.load(TEMPLATE_PATH, process=False, force="mesh")
    topology = build_topology(mesh)
    a, b = 0, 5000
    geo = geodesic_distance(mesh, topology, a, b)
    straight = straight_distance(mesh, a, b)
    assert geo >= straight - 1e-6


def test_geodesic_distance_same_vertex_is_zero():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    v = _vertex_index(3, 1, 1)
    assert geodesic_distance(mesh, topology, v, v) == 0.0


def test_geodesic_distance_raises_on_disconnected_islands():
    island_a = _grid_mesh(2, 2)
    island_b = _grid_mesh(2, 2)
    island_b.vertices += np.array([100.0, 100.0, 0.0])  # far away, no shared vertices/edges
    combined = trimesh.Trimesh(
        vertices=np.vstack([island_a.vertices, island_b.vertices]),
        faces=np.vstack([island_a.faces, island_b.faces + len(island_a.vertices)]),
        process=False,
    )
    topology = build_topology(combined)

    with pytest.raises(ValueError, match="disconnected"):
        geodesic_distance(combined, topology, 0, len(island_a.vertices))


def test_geodesic_path_vertices_starts_and_ends_at_the_query_points():
    # a 4x2 grid's bottom row (y=0) is a direct chain of mesh edges - any
    # route via row 1 would be longer, so the shortest path is provably
    # exactly the bottom row itself.
    mesh = _grid_mesh(4, 2)
    topology = build_topology(mesh)
    a, b = _vertex_index(4, 0, 0), _vertex_index(4, 3, 0)
    path = geodesic_path_vertices(mesh, topology, a, b)
    assert path[0] == a
    assert path[-1] == b
    assert path == [
        _vertex_index(4, 0, 0),
        _vertex_index(4, 1, 0),
        _vertex_index(4, 2, 0),
        _vertex_index(4, 3, 0),
    ]


# --- build_area_boundary / enclosed_area ------------------------------------


def test_enclosed_area_of_a_grid_sub_region_matches_hand_computed_area():
    # a 5x5 grid of cells (6x6 vertices); the boundary loop around the
    # interior 3x3-cell block (corners (1,1)-(4,1)-(4,4)-(1,4)) encloses
    # exactly 3*3 = 9 unit cells, each of area 1.0 - an exact expected value.
    mesh = _grid_mesh(6, 6)
    topology = build_topology(mesh)
    corners = [
        _vertex_index(6, 1, 1),
        _vertex_index(6, 4, 1),
        _vertex_index(6, 4, 4),
        _vertex_index(6, 1, 4),
    ]
    boundary = build_area_boundary(mesh, topology, corners)
    assert enclosed_area(mesh, boundary) == pytest.approx(9.0)


def test_enclosed_area_reuses_the_same_boundary_topology_across_different_meshes():
    # THE central efficiency claim: a BoundaryTopology computed once (on the
    # template) gives correct, DIFFERENT areas when reused unchanged against
    # two different meshes sharing that same topology - no re-flood-fill.
    template = _grid_mesh(6, 6)
    topology = build_topology(template)
    corners = [
        _vertex_index(6, 1, 1),
        _vertex_index(6, 4, 1),
        _vertex_index(6, 4, 4),
        _vertex_index(6, 1, 4),
    ]
    boundary = build_area_boundary(template, topology, corners)

    stretched = trimesh.Trimesh(vertices=template.vertices * [2.0, 1.0, 1.0], faces=template.faces, process=False)

    area_template = enclosed_area(template, boundary)
    area_stretched = enclosed_area(stretched, boundary)
    assert area_template == pytest.approx(9.0)
    assert area_stretched == pytest.approx(18.0)  # doubled in x -> doubled area
    assert area_stretched != area_template


def test_build_area_boundary_rejects_fewer_than_3_points():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    with pytest.raises(ValueError, match="at least 3"):
        build_area_boundary(mesh, topology, [0, 1])


def test_build_area_boundary_rejects_a_boundary_that_does_not_enclose_anything():
    # the mesh's own OUTER perimeter is never part of face_adjacency (a
    # boundary edge only ever belongs to one face) - tracing it removes
    # nothing from the graph, so it can't separate the mesh into two pieces.
    mesh = _grid_mesh(4, 4)
    topology = build_topology(mesh)
    outer_corners = [
        _vertex_index(4, 0, 0),
        _vertex_index(4, 3, 0),
        _vertex_index(4, 3, 3),
        _vertex_index(4, 0, 3),
    ]
    with pytest.raises(ValueError, match="doesn't enclose"):
        build_area_boundary(mesh, topology, outer_corners)


# --- compute_measurement dispatch ------------------------------------------


def test_compute_measurement_linear_straight_vs_geodesic():
    mesh = _grid_mesh(4, 4)
    topology = build_topology(mesh)
    a, b = _vertex_index(4, 0, 0), _vertex_index(4, 3, 0)
    straight = compute_measurement(mesh, topology, "linear", [a, b], geodesic=False)
    geo = compute_measurement(mesh, topology, "linear", [a, b], geodesic=True)
    assert straight == pytest.approx(3.0)
    assert geo == pytest.approx(3.0)


def test_compute_measurement_linear_rejects_wrong_point_count():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    with pytest.raises(ValueError, match="exactly 2"):
        compute_measurement(mesh, topology, "linear", [0, 1, 2])


def test_compute_measurement_angular_rejects_wrong_point_count():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    with pytest.raises(ValueError, match="exactly 3"):
        compute_measurement(mesh, topology, "angular", [0, 1])


def test_compute_measurement_area_requires_a_precomputed_boundary():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    with pytest.raises(ValueError, match="boundary topology precomputed"):
        compute_measurement(mesh, topology, "area", [0, 1, 2])


def test_compute_measurement_rejects_unknown_type():
    mesh = _grid_mesh(3, 3)
    topology = build_topology(mesh)
    with pytest.raises(ValueError, match="unknown measurement type"):
        compute_measurement(mesh, topology, "volume", [0, 1])
