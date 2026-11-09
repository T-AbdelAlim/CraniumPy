"""repairing holes and resampling down to a target vertex count.

old app used pymeshfix for repair and pyacvd (voronoi clustering) for
resampling - both from gui_methods.py's repairsample, old repo.

repair_mesh has two methods:
  - "pymeshfix" (default) - the real pymeshfix engine
    (pymeshfix._meshfix.clean_from_arrays), fully in memory, no pyvista/VTK
    needed for this (pymeshfix's own `pip show` lists numpy only - pyvista
    is an optional extra of that package we're not installing). gets a real
    scan fully watertight and winding-consistent, which the trimesh method
    below can't manage.
  - "trimesh" - just trimesh's own process()/fill_holes()/fix_winding.
    noticeably worse at closing bigger/messier holes - winding-consistent
    but not actually watertight. kept as a fallback in case pymeshfix is
    ever a pain to install somewhere.

resample_mesh has two methods too:
  - "quadric" (default) - quadric decimation via fast_simplification, a
    small standalone package, no pyvista/VTK. it targets a face count, not
    vertex count, so I approximate with 2 * n_vertices (roughly the
    face:vertex ratio for a closed triangle mesh, euler's formula).
  - "voronoi" - actual centroidal voronoi / ACVD-style clustering (what
    pyacvd does) needs pyvista/VTK, no way around it - pyacvd's Clustering
    class is built directly on pyvista.PolyData. not implementing it for
    now to keep the install lean. if uniform resampling ever matters more
    than staying lean, this is the one spot VTK would come back in.
"""

from __future__ import annotations

import threading
from typing import Literal

import numpy as np
import trimesh

RepairMethod = Literal["pymeshfix", "trimesh"]
ResampleMethod = Literal["quadric", "voronoi"]

# fast_simplification isn't thread-safe: two decimations running at once
# (the Longitudinal workspace measures every staged timepoint in parallel)
# can hand back faces that point past the end of the vertex array, and
# trimesh then fails with an IndexError. one at a time fixes it, and a
# decimation is quick enough that the wait doesn't matter.
_decimation_lock = threading.Lock()


def repair_mesh(mesh: trimesh.Trimesh, method: RepairMethod = "pymeshfix") -> trimesh.Trimesh:
    """cleans up degenerate/duplicate faces, fixes winding, fills holes.
    pymeshfix (default) does a noticeably better job closing up real scans
    than the trimesh method - use trimesh only if you want to avoid the
    pymeshfix dependency.

    merges coincident vertices first, regardless of method. matters because
    some real scans (photogrammetry .obj exports) have duplicate vertices
    at the seams between reconstructed patches that never got welded on
    export - pymeshfix keeps only the largest connected component and
    drops everything else, so unwelded seams can silently throw away most
    of the head. merge_vertices() only touches vertices that are already
    coincident (within trimesh's default tolerance), so it's welding what
    should've been welded on export, not simplifying anything.

    drops texture/UV/material before that merge - merge_vertices() treats
    two vertices with different UV as different even at the same 3D
    position (correct for a real UV seam), which on a textured scan means
    only about half as many duplicates get merged. repair can't preserve
    texture through pymeshfix anyway (clean_from_arrays only takes bare
    vertices/faces), so there's nothing lost by dropping it here."""
    mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
    mesh.merge_vertices()

    if method == "pymeshfix":
        from pymeshfix import _meshfix

        vertices, faces = _meshfix.clean_from_arrays(np.asarray(mesh.vertices), np.asarray(mesh.faces))
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    if method == "trimesh":
        mesh.process(validate=True)
        trimesh.repair.fill_holes(mesh)
        return mesh

    raise ValueError(f"unknown repair method {method!r}")


def keep_largest_component(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """drops every connected component except the largest one (by face
    count). no-op if the mesh is already a single component.

    clipping.py's cranial_clip chains a couple of extra safety cuts (a
    sphere trim, an angled plane for stray rear/neck geometry) on top of
    the real landmark-plane boundary. on an unusually-shaped head those
    extra cuts can graze the surface at a shallow angle instead of passing
    cleanly through, leaving a scatter of tiny disconnected slivers behind.

    repair can't be the fix here even though it's the usual tool for
    fragmentation - it runs before clip in harmonize(), not after,
    specifically so it can't cap the hole clipping is supposed to leave
    open. and this isn't a hole to fill anyway, it's debris to throw away.
    resample happens to hide this by accident (quadric decimation merges
    small fragments back into the main body as a side effect), so it only
    shows up with resampling off."""
    components = mesh.split(only_watertight=False)
    if len(components) <= 1:
        return mesh
    return max(components, key=lambda c: len(c.faces))


def keep_component_at(mesh: trimesh.Trimesh, point) -> trimesh.Trimesh:
    """keeps the connected component closest to `point` (the largest of them
    if several touch it), drops the rest. for a clip that should keep a
    known anatomical region - the face, around sellion - where "largest"
    isn't a safe stand-in: on a scan with a lot of chest or shoulder in front
    of the body, the facial clip's cuts can separate the face from a chest
    region that's bigger than the face itself."""
    components = mesh.split(only_watertight=False)
    if len(components) <= 1:
        return mesh
    point = np.asarray(point, dtype=np.float64).reshape(1, 3)
    distances = [float(np.min(np.linalg.norm(np.asarray(c.vertices) - point, axis=1))) for c in components]
    nearest = min(distances)
    candidates = [c for c, d in zip(components, distances) if d <= nearest + 1.0]
    return max(candidates, key=lambda c: len(c.faces))


def _face_aspect_ratios(mesh: trimesh.Trimesh) -> np.ndarray:
    """longest-edge-squared over area, normalized so an equilateral triangle
    scores 1.0 - the standard triangle quality metric. climbs fast for thin
    slivers (a triangle that's basically a line scores in the hundreds)."""
    v = mesh.vertices[mesh.faces]
    a = np.linalg.norm(v[:, 0] - v[:, 1], axis=1)
    b = np.linalg.norm(v[:, 1] - v[:, 2], axis=1)
    c = np.linalg.norm(v[:, 2] - v[:, 0], axis=1)
    s = (a + b + c) / 2
    area = np.sqrt(np.maximum(s * (s - a) * (s - b) * (s - c), 1e-12))
    longest = np.maximum(np.maximum(a, b), c)
    return (longest**2) / (4 * np.sqrt(3) * np.maximum(area, 1e-12))


def _boundary_face_mask(mesh: trimesh.Trimesh) -> np.ndarray:
    """True for faces that own at least one open-boundary edge (an edge used
    by only this one face, not shared with a neighbor)."""
    group = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    mask = np.zeros(len(mesh.faces), dtype=bool)
    if len(group) == 0:
        return mask
    mask[np.unique(mesh.edges_face[group])] = True
    return mask


def trim_boundary_slivers(
    mesh: trimesh.Trimesh, max_aspect_ratio: float = 3.0, max_passes: int = 8
) -> trimesh.Trimesh:
    """drops genuinely degenerate (near-zero-area) sliver triangles right at
    an open mesh boundary - just the pathological ones. general boundary
    jaggedness is clean_boundary's job (below); this is a narrower safety
    net so a handful of near-zero-area triangles, which can wreck normals
    or volume calculations, don't survive.

    a plane clip that grazes the surface at a shallow angle leaves some
    near-degenerate triangles right at the cut - each one really is the
    mesh intersected with the plane, just stretched almost to a line.
    dropping the worst of them retreats the open boundary to the next real
    edge loop.

    a handful of passes can be needed since removing one tooth sometimes
    exposes another thin triangle right behind it - stops as soon as a
    pass finds nothing over the threshold. runs keep_largest_component
    after every pass since eroding the boundary can occasionally strand a
    sliver of mesh that was only still attached through triangles just
    removed."""
    for _ in range(max_passes):
        boundary = _boundary_face_mask(mesh)
        ar = _face_aspect_ratios(mesh)
        drop = boundary & (ar > max_aspect_ratio)
        if not drop.any():
            break
        mesh = mesh.submesh([np.nonzero(~drop)[0]], append=True)
        mesh = keep_largest_component(mesh)
    return mesh


def _boundary_loops(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """chains the open-boundary edges into ordered vertex-index loops -
    walks vertex -> next-vertex until each loop closes.

    works because mesh.edges preserves each face's own winding order, and
    a manifold-with-boundary mesh's boundary edges (each used by exactly
    one face) chain head-to-tail into simple closed cycles - no need to
    sort or match anything up by position, just follow the chain. drops
    any loop that doesn't close cleanly (a pinch point touching two holes,
    say) rather than guessing - rare, and a skipped loop just means that
    hole's edge doesn't get smoothed, nothing worse."""
    group = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    if len(group) == 0:
        return []
    next_vertex = dict(mesh.edges[group].tolist())

    loops = []
    visited: set[int] = set()
    for start in next_vertex:
        if start in visited:
            continue
        loop = [start]
        visited.add(start)
        cur = next_vertex.get(start)
        closed = False
        while cur is not None:
            if cur == start:
                closed = True
                break
            if cur in visited:
                break
            loop.append(cur)
            visited.add(cur)
            cur = next_vertex.get(cur)
        if closed and len(loop) >= 4:
            loops.append(np.array(loop, dtype=np.int64))
    return loops


def _relax_boundary_loops_once(mesh: trimesh.Trimesh, factor: float) -> trimesh.Trimesh:
    """one Jacobi relaxation step: every open-boundary vertex moves partway
    toward the midpoint of its two loop-neighbors, in place along the loop
    only - interior vertices don't move.

    every boundary vertex is already exactly coplanar (it's a plane/mesh
    edge intersection) - averaging coplanar points stays coplanar, so
    there's no need to reproject onto the clip plane after this. what
    moves is position along the loop's own curve: same idea as Laplacian
    mesh smoothing but restricted to the 1D boundary curve. recomputes the
    loops fresh every call since clean_boundary calls this between
    face-dropping steps that renumber vertices."""
    loops = _boundary_loops(mesh)
    if not loops:
        return mesh
    mesh = mesh.copy()
    verts = mesh.vertices.copy()
    for loop in loops:
        n = len(loop)
        idx = np.arange(n)
        prev = verts[loop[(idx - 1) % n]]
        nxt = verts[loop[(idx + 1) % n]]
        midpoint = (prev + nxt) / 2
        verts[loop] = verts[loop] + factor * (midpoint - verts[loop])
    mesh.vertices = verts
    return mesh


def _loops_from_edges(edges: np.ndarray, boundary_group: np.ndarray) -> list[np.ndarray]:
    """_boundary_loops on plain arrays - the same chain walk, fed the
    already-found boundary edges instead of a mesh."""
    if len(boundary_group) == 0:
        return []
    next_vertex = dict(edges[boundary_group].tolist())
    loops = []
    visited: set[int] = set()
    for start in next_vertex:
        if start in visited:
            continue
        loop = [start]
        visited.add(start)
        cur = next_vertex.get(start)
        closed = False
        while cur is not None:
            if cur == start:
                closed = True
                break
            if cur in visited:
                break
            loop.append(cur)
            visited.add(cur)
            cur = next_vertex.get(cur)
        if closed and len(loop) >= 4:
            loops.append(np.array(loop, dtype=np.int64))
    return loops


def _aspect_ratios(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    v = vertices[faces]
    a = np.linalg.norm(v[:, 0] - v[:, 1], axis=1)
    b = np.linalg.norm(v[:, 1] - v[:, 2], axis=1)
    c = np.linalg.norm(v[:, 2] - v[:, 0], axis=1)
    s = (a + b + c) / 2
    area = np.sqrt(np.maximum(s * (s - a) * (s - b) * (s - c), 1e-12))
    longest = np.maximum(np.maximum(a, b), c)
    return (longest**2) / (4 * np.sqrt(3) * np.maximum(area, 1e-12))


def _edge_groups(faces: np.ndarray, n_vertices: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """one sort of the face edges, giving what group_rows(edges_sorted, 1)
    and group_rows(edges_sorted, 2) would: the open-boundary edges (used by
    one face) and the interior edge pairs (used by exactly two). each edge
    is keyed on (larger, smaller) vertex index, the order trimesh's own row
    hash sorts in, so the boundary edges come out in the same order - that
    order decides which loop a pinch vertex is walked into."""
    edges = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    lo = np.minimum(edges[:, 0], edges[:, 1])
    hi = np.maximum(edges[:, 0], edges[:, 1])
    keys = hi * np.int64(n_vertices) + lo
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
    counts = np.diff(np.r_[starts, len(keys)])
    boundary = order[starts[counts == 1]]
    pair_starts = starts[counts == 2]
    pairs = np.stack([order[pair_starts], order[pair_starts + 1]], axis=1)
    return edges, boundary, pairs


def _single_component(n_faces: int, pairs: np.ndarray) -> bool:
    """whether every face is reachable from every other through a shared
    edge - the same face adjacency trimesh's split() walks (an edge used by
    exactly two faces), just without building any meshes to find out."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    if len(pairs) == 0:
        return n_faces <= 1
    adjacency = pairs // 3
    graph = coo_matrix((np.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])), shape=(n_faces, n_faces))
    count, _ = connected_components(graph, directed=False)
    return count == 1


def clean_boundary(
    mesh: trimesh.Trimesh, rounds: int = 30, max_aspect_ratio: float = 3.0, smooth_factor: float = 0.5
) -> trimesh.Trimesh:
    """the actual post-clip boundary cleanup - relaxes the open boundary
    into a smooth curve while continuously trimming away whatever that
    relaxation turns into a degenerate triangle, so the two don't fight
    each other.

    a landmark plane that runs close to tangent to the head's surface for
    a long stretch (not just one grazing spot) leaves hundreds of
    perfectly ordinary-shaped triangles, each stepping up or down a couple
    mm as the plane wanders in and out of the surface. no aspect-ratio
    threshold catches an ordinary triangle, but the sawtooth is very
    visible in the viewer since it runs around the whole rim.

    relaxing the boundary loop on its own isn't safe either: a boundary
    triangle often has two of its three vertices on the loop, and moving
    those two independently - each toward its own loop neighbors, with no
    idea they share a triangle - can slide them together or into a
    straight line with the third vertex, collapsing a normal triangle into
    a worse sliver than the raw clip produced. interleaving fixes both:
    relax one step, immediately drop whatever that step just turned into
    a sliver (retreating the loop by one vertex right there instead of
    letting the next step smooth an already-collapsing triangle), repeat.
    converges to a boundary of close-to-equilateral triangles after a few
    dozen rounds, dropping a small fraction of the mesh's faces total.

    each round is exactly _relax_boundary_loops_once followed by one
    trim_boundary_slivers pass, but run on plain vertex/face arrays: the
    mesh-object version rebuilt every trimesh cache (and split the mesh
    into components) several times a round, which made this the slowest
    part of a clip. the boundary edges are found once a round and shared
    by the relax and the trim (relaxing moves vertices, not connectivity),
    vertices are renumbered the same way submesh() does it, and the rare
    trim that actually breaks the mesh apart is handed to
    keep_largest_component itself, so the result is the same mesh."""
    vertices = np.array(mesh.vertices, dtype=np.float64)
    faces = np.array(mesh.faces, dtype=np.int64)
    groups = None
    for _ in range(rounds):
        edges, boundary_group, _pairs = groups or _edge_groups(faces, len(vertices))
        groups = None
        loops = _loops_from_edges(edges, boundary_group)
        if not loops:
            break

        for loop in loops:
            n = len(loop)
            idx = np.arange(n)
            midpoint = (vertices[loop[(idx - 1) % n]] + vertices[loop[(idx + 1) % n]]) / 2
            vertices[loop] = vertices[loop] + smooth_factor * (midpoint - vertices[loop])

        # only faces on the open boundary can be dropped, so only theirs
        # are measured.
        boundary_faces = np.unique(boundary_group // 3)
        drop = np.zeros(len(faces), dtype=bool)
        drop[boundary_faces[_aspect_ratios(vertices, faces[boundary_faces]) > max_aspect_ratio]] = True
        if not drop.any():
            continue

        faces = faces[~drop]
        used, inverse = np.unique(faces.reshape(-1), return_inverse=True)
        vertices = vertices[used]
        faces = inverse.reshape(-1, 3)
        groups = _edge_groups(faces, len(vertices))
        if not _single_component(len(faces), groups[2]):
            kept = keep_largest_component(trimesh.Trimesh(vertices=vertices, faces=faces, process=False))
            vertices = np.array(kept.vertices, dtype=np.float64)
            faces = np.array(kept.faces, dtype=np.int64)
            groups = None
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def resample_mesh(mesh: trimesh.Trimesh, n_vertices: int, method: ResampleMethod = "quadric") -> trimesh.Trimesh:
    """resamples down to roughly n_vertices. does nothing if the mesh already
    has fewer verts than that, or if it's huge (>500k, same bail-out the old
    app had for "mesh contains too many vertices")."""
    if mesh.vertices.shape[0] <= n_vertices or mesh.vertices.shape[0] > 500_000:
        return mesh

    if method == "quadric":
        target_faces = max(4, n_vertices * 2)
        with _decimation_lock:
            return mesh.simplify_quadric_decimation(face_count=target_faces)

    if method == "voronoi":
        raise NotImplementedError(
            "voronoi/ACVD resampling needs pyvista+VTK, not installed by default - see the "
            "module docstring for why. use method='quadric' instead for now."
        )

    raise ValueError(f"unknown resample method {method!r}")
