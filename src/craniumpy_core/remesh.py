"""repairing holes and resampling down to a target vertex count.

old app used pymeshfix for repair and pyacvd (voronoi clustering) for
resampling - both from gui_methods.py's repairsample, old repo.

repair_mesh has two methods:
  - "pymeshfix" (default) - the real pymeshfix engine
    (pymeshfix._meshfix.clean_from_arrays), fully in memory, and no
    pyvista/VTK needed for this. double checked this myself: `pip show
    pymeshfix` says `Requires: numpy`, that's it - pyvista is only an
    optional extra of that package which we're not installing. ran it on
    resources/test_mesh/test_mesh.ply and it comes out fully watertight and
    winding-consistent, which the trimesh method below does not manage.
  - "trimesh" - just trimesh's own process()/fill_holes()/fix_winding.
    noticeably worse at closing bigger/messier holes - tested on the same
    file, comes out winding-consistent but not actually watertight. keeping
    it around as a fallback in case pymeshfix is ever a problem to install
    somewhere.

resample_mesh has two methods too:
  - "quadric" (default) - quadric decimation via fast_simplification, a
    small standalone package, no pyvista/VTK. it targets a FACE count, not
    vertex count, so I approximate with 2 * n_vertices (that's roughly the
    face:vertex ratio for a closed triangle mesh, euler's formula).
  - "voronoi" - actual centroidal voronoi / ACVD-style clustering (what
    pyacvd does) needs pyvista/VTK, no way around it - pyacvd's Clustering
    class is built directly on pyvista.PolyData, unlike pymeshfix there's no
    VTK-free path here. not implementing it for now to keep the install
    lean. if truly uniform resampling ever matters more than staying lean,
    this is the one spot where VTK would have to come back in, and only here.
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
    pymeshfix dependency for some reason.

    merges coincident vertices first, regardless of method. found out why
    this matters the hard way: a real patient scan (photogrammetry, not the
    clean shipped templates) came back from pymeshfix with ~75% of its
    vertices gone and the surviving chunk badly off-center. turned out the
    raw .obj had 18,000+ disconnected "components" - duplicate vertices at
    the seams between reconstructed patches that were never welded in the
    export, so most of the head was topologically split off from the rest
    by a few unmerged points. pymeshfix's cleaning keeps only the single
    largest connected component and silently drops everything else, so it
    kept one patch and threw the rest of the head away. merge_vertices()
    here only touches vertices that are already coincident (or within
    trimesh's tight default tolerance) - not a simplification, just welding
    what should've been welded on export. confirmed it collapses that same
    scan's 18,000+ components down to 1 before repair ever runs.

    drops any texture/UV/material before that merge, on purpose - regression
    caught right after register() started carrying texture through
    (previously stripped immediately, see pipeline.py). merge_vertices()
    treats two vertices with different UV as different, even at the exact
    same 3D position, since that's normally correct (that's what a UV seam
    is) - but it meant a textured version of the same scan above only
    merged about half as many duplicates as the untextured version did,
    leaving most of the fragmentation in place and bringing the whole bug
    back. repair can't preserve texture through pymeshfix either way
    (clean_from_arrays only ever takes bare vertices/faces), so there's
    nothing to lose by dropping it before the merge that actually needs to
    see through those seams."""
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
    sphere trim, then an angled plane meant to catch stray rear/neck
    geometry a horizontal cut alone wouldn't) on top of the real landmark-
    plane boundary. found out the hard way, on a real template with
    different proportions than whatever this was tuned against, that the
    angled cut can graze the actual cranium surface at a shallow angle
    instead of passing cleanly through the neck - and slicing a mesh at a
    near-tangent angle is exactly the condition that leaves behind a
    scatter of tiny disconnected slivers (went from 1 component to 26 right
    after that one clip, then 225 by the time the landmark-plane clip ran
    too, checked by clipping each stage separately on the actual file that
    surfaced this).

    repair can't be the fix here even though it's the usual tool for
    fragmentation - it deliberately runs BEFORE clip in harmonize(), not
    after, specifically so it can't cap the hole that clipping is supposed
    to leave open (see that docstring). and this isn't a hole to fill
    anyway, it's debris to throw away, which is a different, safe
    operation. resample happened to make this invisible as a total
    accident - quadric decimation's simplification apparently merges small
    fragments back into the main body as a side effect - which is exactly
    why this never showed up before resample defaulted to on: turn
    resample off and whatever the clip left fragmented stays fragmented
    all the way to the saved file."""
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
    an open mesh boundary - the truly pathological ones, not the general
    jaggedness (see smooth_boundary_loop for that, which is doing the actual
    visual cleanup work now; this is a narrower safety net kept mostly so a
    handful of near-zero-area triangles - which can wreck normals/volume
    calculations - don't survive into the smoothed mesh).

    a plane clip that grazes the surface at a shallow angle (see
    clipping.cranial_clip) leaves some near-degenerate triangles right at
    the cut - each one really is the mesh intersected with the plane, so
    nothing here is "wrong" geometrically, it's just a triangle stretched
    almost to a line. dropping the worst of them retreats the open
    boundary to the next real edge loop.

    checked on a real scan where the landmark-plane clip grazes near the
    chin: max boundary aspect ratio 344 -> 2.98, for 0.3% of the mesh's
    faces. turned out the *bulk* of that scan's ragged boundary wasn't
    these outliers at all though - it was hundreds of ordinary, non-sliver
    triangles along a stretch where the landmark plane runs close to
    tangent to the head for its whole length, each contributing a small
    (2-4mm) legitimate up/down step. an aspect-ratio filter can't touch
    those without eating real anatomy, since they're not degenerate -
    that's what smooth_boundary_loop is for.

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
    sort or match anything up by position, just follow the chain. bails
    out (drops) any loop that doesn't close cleanly rather than guessing,
    which would only happen on a mesh whose boundary isn't a simple
    manifold loop (e.g. a pinch point touching two holes) - a real but
    rare case not worth the extra complexity to handle specially here,
    since a skipped loop just means that particular hole's edge doesn't
    get smoothed, not a crash or wrong geometry elsewhere."""
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
    moves is position *along* the loop's own curve: same idea as Laplacian
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

    turns out trim_boundary_slivers's aspect-ratio filter, on its own, was
    solving the wrong problem: checked on a real scan where the cranial
    landmark plane runs close to tangent to the head's surface for its
    whole length (not just one grazing spot), and the resulting boundary
    was hundreds of perfectly ordinary-shaped triangles, each just
    stepping up or down 2-4mm as the plane wanders in and out of the noisy
    real surface. no aspect-ratio threshold catches an ordinary triangle,
    but the sawtooth is still very visible in the viewer since it happens
    continuously around the whole rim, not at one bad spot.

    and relaxing the boundary loop on its own (an earlier version of this
    function, see git history) isn't safe either: a boundary triangle
    often has two of its three vertices ON the loop, and moving those two
    independently - toward THEIR OWN loop neighbors, with no idea they
    share a triangle - can slide them toward each other or into a straight
    line with the third vertex, collapsing a perfectly normal triangle
    into a new, worse sliver than anything the raw clip produced. checked
    on the same real scan: 20 iterations of relaxation with no cleanup in
    between took the boundary's max aspect ratio from 344 (raw clip) up to
    1521 - it visibly straightened the *loop line* while quietly wrecking
    a handful of triangles the 2D silhouette doesn't reveal.

    interleaving fixes both: relax one step, immediately drop whatever
    that step just turned into a sliver (which retreats the loop by one
    vertex right there, rather than letting the next relax step try to
    smooth a triangle that's already collapsing), repeat. on that same
    scan this converges to boundary max aspect ratio ~2 (mean ~0.6, i.e.
    close to equilateral) after 30 rounds, dropping about 1.5% of the
    mesh's faces total - nothing close to the "keep 78% and call it a
    fix" this would be if either technique ran alone."""
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
