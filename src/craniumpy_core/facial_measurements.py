"""geometry primitives for the Facial Anthropometrics workspace: point-to-point
straight/geodesic distance, angle, and enclosed mesh surface area, given
landmarks as VERTEX INDICES (not free 3D points) on a mesh.

vertex indices, not raw points, is the load-bearing design choice here - it's
the same guarantee registration.nicp.register_template already relies on
(see that module, and cohort.py's own docstring): any mesh fit to the same
template shares that template's exact vertex count, order, and face
connectivity. so a landmark defined once, as a nearest-vertex snap on the
template (see nearest_vertex_index), transfers to every other same-template
mesh as a plain O(1) index lookup - no per-mesh re-registration, no nearest-
point search, ever.

that same fact is what makes the expensive parts of this module cheap in
practice: MeshTopology (the edge graph) and BoundaryTopology (which faces an
area boundary encloses) depend only on face CONNECTIVITY, which is identical
across every mesh sharing a template - so both are meant to be computed once
per template and reused, unchanged, for every batch mesh. only the numeric
parts that actually depend on a mesh's own geometry (edge weights for
geodesic distance, per-face areas for the area sum) are cheap, vectorized,
per-mesh work. this module itself holds no cache - see api/routers/facial.py
for where MeshTopology/BoundaryTopology actually get reused across a batch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree


@dataclass
class MeshTopology:
    """the parts of a mesh's connectivity that stay identical across every
    mesh sharing the same NICP template - build_topology(template) once,
    reuse for every batch mesh's own geodesic_distance/build_area_boundary
    call (passing that mesh's own vertices for the actual distances)."""

    edges_unique: np.ndarray  # (E, 2) int - vertex index pairs, from trimesh's own edges_unique
    face_adjacency: np.ndarray  # (A, 2) int - adjacent face-index pairs
    face_adjacency_edges: np.ndarray  # (A, 2) int - the shared vertex-index edge per adjacent face pair
    n_vertices: int
    n_faces: int


def build_topology(template: trimesh.Trimesh) -> MeshTopology:
    return MeshTopology(
        edges_unique=np.asarray(template.edges_unique),
        face_adjacency=np.asarray(template.face_adjacency),
        face_adjacency_edges=np.asarray(template.face_adjacency_edges),
        n_vertices=len(template.vertices),
        n_faces=len(template.faces),
    )


def nearest_vertex_index(mesh: trimesh.Trimesh, point, kdtree: cKDTree | None = None) -> int:
    """snaps a raw 3D point (e.g. a raycast hit from ctrl-click picking) to
    its nearest vertex on `mesh` - same cKDTree-nearest-neighbor pattern
    already used throughout this package (pipeline.py, registration/rigid.py,
    registration/nicp.py) for point matching. pass a prebuilt kdtree (e.g.
    cached per template) to avoid rebuilding it on every pick."""
    tree = kdtree if kdtree is not None else cKDTree(mesh.vertices)
    _, idx = tree.query(np.asarray(point, dtype=float))
    return int(idx)


def straight_distance(mesh: trimesh.Trimesh, a: int, b: int) -> float:
    """plain 3D Euclidean distance between two vertices - the Linear
    measurement's default mode, and always what Angular's two segments use."""
    verts = np.asarray(mesh.vertices)
    return float(np.linalg.norm(verts[a] - verts[b]))


def angle_degrees(mesh: trimesh.Trimesh, a: int, vertex: int, c: int) -> float:
    """the angle at `vertex`, between straight 3D rays to `a` and `c` - always
    straight-line, never geodesic (Angular measurements have no surface-path
    toggle, per the workspace's own spec)."""
    verts = np.asarray(mesh.vertices)
    v1 = verts[a] - verts[vertex]
    v2 = verts[c] - verts[vertex]
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        raise ValueError("angle is undefined - two of the three points coincide")
    cos_theta = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_theta)))


def _weighted_graph(mesh: trimesh.Trimesh, topology: MeshTopology) -> csr_matrix:
    """the per-mesh part of geodesic distance: topology.edges_unique (fixed,
    shared across every same-template mesh) gives WHICH vertex pairs are
    edges; only the edge LENGTHS depend on this specific mesh's own vertex
    positions, so that's the only thing recomputed here. undirected (each
    edge written both ways) since surface distance has no direction."""
    edges = topology.edges_unique
    verts = np.asarray(mesh.vertices)
    weights = np.linalg.norm(verts[edges[:, 0]] - verts[edges[:, 1]], axis=1)
    rows = np.concatenate([edges[:, 0], edges[:, 1]])
    cols = np.concatenate([edges[:, 1], edges[:, 0]])
    data = np.concatenate([weights, weights])
    n = topology.n_vertices
    return csr_matrix((data, (rows, cols)), shape=(n, n))


def geodesic_distance(mesh: trimesh.Trimesh, topology: MeshTopology, a: int, b: int) -> float:
    """shortest path along the mesh surface (graph distance over mesh edges,
    Dijkstra) between two vertices - Linear measurement's "shortest distance
    along the mesh surface" mode. raises ValueError if the mesh's edge graph
    doesn't actually connect a to b (a genuinely disconnected mesh, or a
    or b sitting on an isolated component)."""
    if a == b:
        return 0.0
    graph = _weighted_graph(mesh, topology)
    dist = dijkstra(graph, indices=[a], directed=False)
    d = float(dist[0, b])
    if not np.isfinite(d):
        raise ValueError(
            f"no path along the mesh surface between vertex {a} and vertex {b} - "
            "these two landmarks sit on disconnected parts of the mesh"
        )
    return d


def geodesic_path_vertices(mesh: trimesh.Trimesh, topology: MeshTopology, a: int, b: int) -> list[int]:
    """the actual ordered vertex-index route of geodesic_distance's shortest
    path (not just its length) - used to trace a Surface Area boundary
    between consecutive landmark points. raises the same ValueError
    geodesic_distance does when a and b aren't connected."""
    if a == b:
        return [a]
    graph = _weighted_graph(mesh, topology)
    dist, predecessors = dijkstra(graph, indices=[a], directed=False, return_predecessors=True)
    if not np.isfinite(dist[0, b]):
        raise ValueError(
            f"no path along the mesh surface between vertex {a} and vertex {b} - "
            "these two landmarks sit on disconnected parts of the mesh"
        )
    path = [b]
    current = b
    while current != a:
        current = int(predecessors[0, current])
        path.append(current)
    path.reverse()
    return path


def _closed_geodesic_loop(mesh: trimesh.Trimesh, topology: MeshTopology, vertex_indices: list[int]) -> list[int]:
    """chains geodesic_path_vertices between each consecutive pair of
    landmarks, wrapping back from the last to the first - one continuous
    ordered vertex loop tracing the boundary along the mesh surface."""
    loop = [vertex_indices[0]]
    n = len(vertex_indices)
    for i in range(n):
        a = vertex_indices[i]
        b = vertex_indices[(i + 1) % n]
        segment = geodesic_path_vertices(mesh, topology, a, b)
        loop.extend(segment[1:])  # segment[0] == a == loop[-1] already
    return loop


@dataclass
class BoundaryTopology:
    """which faces a Surface Area measurement's landmark boundary encloses -
    topology-only (face indices), computed once on the template (see
    build_area_boundary) and reused unchanged for every same-template batch
    mesh's own enclosed_area call. a per-mesh landmark correction needs a
    fresh BoundaryTopology of its own, built against that one mesh - never
    reuses another mesh's."""

    boundary_vertex_loop: list[int]
    face_indices: np.ndarray  # (K,) int - indices into mesh.faces of the enclosed region


def build_area_boundary(mesh: trimesh.Trimesh, topology: MeshTopology, vertex_indices: list[int]) -> BoundaryTopology:
    """traces a closed geodesic loop through `vertex_indices` (see
    _closed_geodesic_loop), then flood-fills the mesh's face-adjacency graph
    with every adjacency that crosses the loop's own edges removed - this
    necessarily splits the mesh into (at least) two connected pieces, an
    "inside" and an "outside" of the loop. the SMALLER piece (by face count)
    is taken as the enclosed region, since a real anthropometric area
    measurement is a sub-region of the face, never "most of it."

    raises ValueError if fewer than 3 points are given, or if removing the
    boundary's edges doesn't actually separate the mesh into more than one
    piece - an open (non-closing) or self-intersecting boundary, or a mesh
    that was already disconnected in a way the loop can't meaningfully
    partition."""
    if len(vertex_indices) < 3:
        raise ValueError("a surface-area measurement needs at least 3 points")

    loop = _closed_geodesic_loop(mesh, topology, vertex_indices)

    n_verts = topology.n_vertices
    boundary_edge_ids = np.unique(
        np.array(
            [min(loop[i], loop[i + 1]) * n_verts + max(loop[i], loop[i + 1]) for i in range(len(loop) - 1)],
            dtype=np.int64,
        )
    )

    face_adj = topology.face_adjacency
    adj_edges_sorted = np.sort(topology.face_adjacency_edges, axis=1)
    adj_edge_ids = adj_edges_sorted[:, 0].astype(np.int64) * n_verts + adj_edges_sorted[:, 1].astype(np.int64)
    keep = ~np.isin(adj_edge_ids, boundary_edge_ids)
    kept_adj = face_adj[keep]

    n_faces = topology.n_faces
    rows = np.concatenate([kept_adj[:, 0], kept_adj[:, 1]])
    cols = np.concatenate([kept_adj[:, 1], kept_adj[:, 0]])
    data = np.ones(len(rows))
    graph = csr_matrix((data, (rows, cols)), shape=(n_faces, n_faces))
    n_components, labels = connected_components(graph, directed=False)

    if n_components < 2:
        raise ValueError(
            "this boundary doesn't enclose a region - it may not close into a loop, or it crosses itself"
        )
    counts = np.bincount(labels, minlength=n_components)
    smallest_label = int(np.argmin(counts))
    face_indices = np.flatnonzero(labels == smallest_label)
    return BoundaryTopology(boundary_vertex_loop=loop, face_indices=face_indices)


def enclosed_area(mesh: trimesh.Trimesh, boundary: BoundaryTopology) -> float:
    """the real mesh surface area of a Surface Area measurement's enclosed
    region - sum of actual triangle areas, never a flat/projected polygon
    approximation. the only per-mesh work here (boundary.face_indices is
    reused topology, shared across every same-template mesh) - O(len(face_indices))."""
    return float(np.asarray(mesh.area_faces)[boundary.face_indices].sum())


def compute_measurement(
    mesh: trimesh.Trimesh,
    topology: MeshTopology,
    point_type: str,
    vertex_indices: list[int],
    geodesic: bool = False,
    boundary: BoundaryTopology | None = None,
) -> float:
    """dispatches to the right primitive for one measurement, given its
    already-transferred vertex indices on `mesh`. `boundary` is required for
    "area" (the caller - api/routers/facial.py - owns deciding whether to
    reuse a cached BoundaryTopology or build a fresh one, this function never
    caches anything itself)."""
    if point_type == "linear":
        if len(vertex_indices) != 2:
            raise ValueError("a linear measurement needs exactly 2 points")
        a, b = vertex_indices
        return geodesic_distance(mesh, topology, a, b) if geodesic else straight_distance(mesh, a, b)
    if point_type == "angular":
        if len(vertex_indices) != 3:
            raise ValueError("an angular measurement needs exactly 3 points")
        a, vertex, c = vertex_indices
        return angle_degrees(mesh, a, vertex, c)
    if point_type == "area":
        if len(vertex_indices) < 3:
            raise ValueError("a surface-area measurement needs at least 3 points")
        if boundary is None:
            raise ValueError("a surface-area measurement needs its boundary topology precomputed")
        return enclosed_area(mesh, boundary)
    raise ValueError(f"unknown measurement type {point_type!r}")
