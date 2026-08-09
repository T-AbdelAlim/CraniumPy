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
    pymeshfix dependency for some reason."""
    if method == "pymeshfix":
        from pymeshfix import _meshfix

        vertices, faces = _meshfix.clean_from_arrays(np.asarray(mesh.vertices), np.asarray(mesh.faces))
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    if method == "trimesh":
        mesh = mesh.copy()
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
