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

from typing import Literal

import numpy as np
import trimesh

RepairMethod = Literal["pymeshfix", "trimesh"]
ResampleMethod = Literal["quadric", "voronoi"]


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
    dozen rounds, dropping a small fraction of the mesh's faces total."""
    for _ in range(rounds):
        if not _boundary_loops(mesh):
            break
        mesh = _relax_boundary_loops_once(mesh, smooth_factor)
        mesh = trim_boundary_slivers(mesh, max_aspect_ratio=max_aspect_ratio, max_passes=1)
    return mesh


def resample_mesh(mesh: trimesh.Trimesh, n_vertices: int, method: ResampleMethod = "quadric") -> trimesh.Trimesh:
    """resamples down to roughly n_vertices. does nothing if the mesh already
    has fewer verts than that, or if it's huge (>500k, same bail-out the old
    app had for "mesh contains too many vertices")."""
    if mesh.vertices.shape[0] <= n_vertices or mesh.vertices.shape[0] > 500_000:
        return mesh

    if method == "quadric":
        target_faces = max(4, n_vertices * 2)
        return mesh.simplify_quadric_decimation(face_count=target_faces)

    if method == "voronoi":
        raise NotImplementedError(
            "voronoi/ACVD resampling needs pyvista+VTK, not installed by default - see the "
            "module docstring for why. use method='quadric' instead for now."
        )

    raise ValueError(f"unknown resample method {method!r}")
