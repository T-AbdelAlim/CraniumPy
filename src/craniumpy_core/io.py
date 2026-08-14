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

    some .ply files carry an explicit but uniform vertex-color array (every
    vertex literally [255, 255, 255, 255]) even though they're not really
    vertex-painted. trimesh keeps that as real per-vertex color data, which
    round-trips into the exported GLB as a COLOR_0 attribute - the frontend
    then renders it through a plain white material instead of the usual
    beige, which looks grey and doesn't match the later pipeline stages
    (repair_mesh drops visual data, so registered/clipped/final always
    render beige). a real per-vertex-painted scan varies from vertex to
    vertex, so a uniform color is never legitimate data - clearing it here
    means the frontend's own beige fallback applies everywhere, not just
    after repair. leaves a real texture (visual.kind == "texture") alone."""
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


def mesh_to_glb(mesh: trimesh.Trimesh) -> bytes:
    """GLB export for the web viewer - corrects real per-vertex color
    (visual.kind == "vertex", e.g. a 3dMD scanner's .ply export) for glTF's
    COLOR_0 accessor before handing off to trimesh's exporter.

    a scanner's captured vertex color is sRGB-encoded display-ready bytes,
    the same as any ordinary photo/texture - but unlike a texture map
    (which three.js's GLTFLoader knows to flag sRGB via colorSpace),
    glTF's spec defines COLOR_0 as already linear, and three.js takes that
    at face value with no decode step. writing the raw captured bytes
    straight through means the renderer's own linear->sRGB *output*
    encoding lands on top of data that's *already* sRGB - colors get
    washed out toward gray, same failure mode a texture would hit if it
    weren't flagged. pre-decoding sRGB->linear here means what actually
    reaches COLOR_0 is genuinely linear, so the renderer's single
    encoding step reproduces the original captured color once, correctly,
    instead of twice.

    leaves the mesh itself untouched - only affects what this specific
    GLB response contains, not session.mesh or anything saved to disk."""
    if mesh.visual.kind == "vertex":
        colors = mesh.visual.vertex_colors
        rgb = colors[:, :3].astype(np.float64) / 255.0
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        corrected = colors.copy()
        corrected[:, :3] = np.clip(linear * 255.0, 0, 255).round().astype(np.uint8)
        mesh = mesh.copy()
        mesh.visual.vertex_colors = corrected

    # include_normals=True matters - trimesh leaves the NORMAL accessor out
    # entirely otherwise, and without normals the mesh renders solid black
    # in the browser no matter what color it's supposed to be.
    return mesh.export(file_type="glb", include_normals=True)
