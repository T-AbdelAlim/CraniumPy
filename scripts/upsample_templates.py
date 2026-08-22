"""upsamples the shipped template meshes (src/craniumpy_core/templates/) to
~25,000 vertices each, saved alongside the originals as new "_25k" files -
a one-time script, not run at app startup (same pattern as
generate_demo_cohort.py). none of the originals are touched, and nothing
elsewhere in the app switches to using these automatically - see
template_registry.py's SHIPPED_TEMPLATES if/when that should change.

method: subdivide first (trimesh's own Trimesh.subdivide() - plain midpoint
subdivision, every new vertex sits exactly on an existing edge midpoint, so
it changes nothing about the mesh's own shape/position/orientation, just its
resolution - verified directly: the first N vertices of a subdivided mesh
are bit-identical to the original N, and bounds/centroid don't move) until
the vertex count clears the target, then hand off to
craniumpy_core.remesh.resample_mesh's existing quadric decimation (the same
method already used throughout this app to hit a target vertex count) to
trim back down to ~25,000. quadric decimation only removes/merges local
geometry - like subdivision, it applies no rigid transform, so the result
stays in the same coordinate frame as the source (verified: bounds identical
to 1e-5, centroid unchanged to 4 decimal places after subdivide+decimate).

resample_mesh's own vertex-count targeting is approximate by construction
(it targets a FACE count via a fixed 2x vertex:face heuristic, see its own
docstring) - a single pass lands within a couple percent of 25,000, not
exactly on it. this script adds one calibration pass on top: decimate once,
measure how far off the result actually landed, then re-decimate the same
subdivided mesh with a face-count target scaled by the observed correction
factor. same underlying method (quadric decimation) both times, just tuned
for precision - verified this reliably lands within ~0.1% of the target
vs. a couple percent for the plain single pass.

run from the repo root:
    python scripts/upsample_templates.py
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from craniumpy_core.remesh import resample_mesh

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "craniumpy_core" / "templates"
TARGET_VERTICES = 25_000

# template_face's own source - a freshly re-exported copy of the same mesh
# already shipped as template_face.ply (verified identical vertex/face
# count and bounding box against the shipped copy before writing this
# script) - used here only because it's the file actually handed over for
# this upsample; every other template upsamples from its own shipped file.
SOURCES: dict[str, Path] = {
    "template_face": Path(r"C:\Users\TAbde\Downloads\template_face_10k.ply"),
}


def _subdivide_past(mesh: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
    while len(mesh.vertices) < target:
        mesh = mesh.subdivide()
    return mesh


def _decimate_to(mesh: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
    """resample_mesh's own single pass, then one calibrated corrective pass
    (see module docstring) - both quadric decimation, just the second one
    aimed more precisely at `target` using what the first pass's own
    face:vertex ratio turned out to be for this specific mesh."""
    first = resample_mesh(mesh, target, method="quadric")
    if len(first.vertices) == 0:
        return first
    first_target_faces = max(4, target * 2)
    corrected_faces = round(first_target_faces * (target / len(first.vertices)))
    return mesh.simplify_quadric_decimation(face_count=corrected_faces)


def upsample_to_25k(mesh: trimesh.Trimesh, target: int = TARGET_VERTICES) -> trimesh.Trimesh:
    subdivided = _subdivide_past(mesh, target)
    return _decimate_to(subdivided, target)


def main() -> None:
    for path in sorted(TEMPLATES_DIR.glob("*.ply")):
        stem = path.stem
        if stem.endswith("_25k"):
            continue
        source = SOURCES.get(stem, path)
        mesh = trimesh.load(source, process=False, force="mesh")
        upsampled = upsample_to_25k(mesh)
        out_path = TEMPLATES_DIR / f"{stem}_25k.ply"
        upsampled.export(out_path)
        centroid_shift = float(((upsampled.centroid - mesh.centroid) ** 2).sum() ** 0.5)
        print(
            f"{stem}: {len(mesh.vertices)} -> {len(upsampled.vertices)} vertices, "
            f"{len(mesh.faces)} -> {len(upsampled.faces)} faces, "
            f"centroid shift {centroid_shift:.5f} -> {out_path.name}"
        )


if __name__ == "__main__":
    main()
