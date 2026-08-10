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
