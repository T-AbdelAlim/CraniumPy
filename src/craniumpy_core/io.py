"""mesh load/save.

just a thin wrapper around trimesh so nothing else in this package has to
import trimesh directly - keeps the mesh library swappable if I ever need to.
replaces the old registration/write_ply.py and nicp/write_ply.py (three
hand-rolled ASCII PLY writers between the two of them, for some reason) plus
all the pyvista read/write calls scattered around the old gui code.
"""

from pathlib import Path

import numpy as np
import trimesh


def strip_uninteresting_vertex_colors(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """clears a uniform (every vertex the exact same value, almost always
    plain white) vertex-color visual, in place - mutates and returns the
    same mesh for convenient chaining at a load call site.

    some real .ply files (not textured, not really vertex-painted either)
    still carry an explicit but uniform vertex-color array - every vertex
    literally [255, 255, 255, 255]. trimesh happily keeps that as real
    per-vertex color data (visual.kind == "vertex"), which round-trips into
    an exported GLB as a COLOR_0 attribute, which the frontend then
    reasonably treats as "this mesh has real vertex colors" and renders
    through a plain white material instead of the app's usual beige -
    looking flatly grey under the scene lighting, and inconsistent with
    every OTHER stage of the same mesh (repair_mesh drops all visual data
    before it ever gets that far, so the registered/clipped/final stages
    always render beige regardless). a real per-vertex-painted scan varies
    from vertex to vertex; nothing legitimate is uniformly one flat color
    across 100% of its surface - clearing the visual here (not silently
    overriding it to some other color) means the frontend's own default
    beige fallback is what applies, matching every later stage of the
    same mesh. leaves a real texture (visual.kind == "texture") alone."""
    if mesh.visual.kind == "vertex":
        colors = mesh.visual.vertex_colors
        if len(colors) > 0 and np.all(colors == colors[0]):
            mesh.visual = trimesh.visual.color.ColorVisuals(mesh=mesh)
    return mesh


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """load a mesh from .ply/.obj/.stl. process=False is important here - it
    stops trimesh from merging/deduping vertices, which would break the
    vertex index correspondence that landmark-based registration relies on."""
    mesh = trimesh.load(path, process=False, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{path} did not load as a single triangle mesh (got {type(mesh)!r})")
    return strip_uninteresting_vertex_colors(mesh)


def save_mesh(mesh: trimesh.Trimesh, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
