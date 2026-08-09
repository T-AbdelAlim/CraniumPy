"""mesh load/save.

just a thin wrapper around trimesh so nothing else in this package has to
import trimesh directly - keeps the mesh library swappable if I ever need to.
replaces the old registration/write_ply.py and nicp/write_ply.py (three
hand-rolled ASCII PLY writers between the two of them, for some reason) plus
all the pyvista read/write calls scattered around the old gui code.
"""

from pathlib import Path

import trimesh


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """load a mesh from .ply/.obj/.stl. process=False is important here - it
    stops trimesh from merging/deduping vertices, which would break the
    vertex index correspondence that landmark-based registration relies on."""
    mesh = trimesh.load(path, process=False, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{path} did not load as a single triangle mesh (got {type(mesh)!r})")
    return mesh


def save_mesh(mesh: trimesh.Trimesh, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
