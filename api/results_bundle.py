"""builds the results you get after an analysis - meshes, a json report, and
a measurement figure, packaged as CP_{stem}_results/. this is basically the
same stuff the old app wrote next to your file (_rg.ply, _metrics.json etc),
just organized into one folder now instead of a pile of sibling files.

two ways this gets delivered: zipped for a browser download
(build_results_bundle), or written straight to disk next to the original
mesh when we know a real filesystem path for it (write_results_to_folder,
desktop app only - see api/routers/mesh.py's /save endpoint). both go
through _build_report_files so the folder layout and filenames match
either way.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.tri import Triangulation

from craniumpy_core.craniometrics import CranioMeasurements, hc_slice_polygon
from craniumpy_core.asymmetry import AsymmetryResult


def shorten_stem(stem: str) -> str:
    """collapses any embedded dot within an underscore-separated segment of
    the stem, keeping only what's before it - some scanners name files like
    "1016510_20210730.000112_edited", where that middle segment is a
    date-plus-subversion nobody wants spelled out in a results folder name.
    "1016510_20210730.000112_edited" -> "1016510_20210730_edited"."""
    return "_".join(part.split(".", 1)[0] for part in stem.split("_"))


def stem_from_filename(filename: str) -> str:
    """the shortened stem to build a results folder/file names from, given
    an original mesh filename (with its real extension still on it)."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return shorten_stem(stem)


def _measurement_figure(mesh: trimesh.Trimesh, measurements: CranioMeasurements) -> bytes:
    """top-down outline of the HC slice, red line style like the old app
    used to draw, with OFD/BPD spans marked on it too."""
    polygon = hc_slice_polygon(mesh, measurements.slice_height)

    fig = Figure(figsize=(6, 6), dpi=150)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    if polygon is not None and len(polygon) > 2:
        closed = np.vstack([polygon, polygon[0]])
        ax.plot(closed[:, 0], closed[:, 2], color="#d1453d", linewidth=2, label="HC slice")

    ax.plot(
        [measurements.lh_opt[0], measurements.rh_opt[0]],
        [measurements.lh_opt[2], measurements.rh_opt[2]],
        color="#2563eb", linewidth=1.5, linestyle="--", marker="o", markersize=4, label="BPD (breadth)",
    )
    ax.plot(
        [measurements.occ_opt[0], measurements.front_opt[0]],
        [measurements.occ_opt[2], measurements.front_opt[2]],
        color="#16a34a", linewidth=1.5, linestyle="--", marker="o", markersize=4, label="OFD (depth)",
    )

    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("z (mm)")
    ax.set_title(
        f"OFD {measurements.depth_mm}mm  BPD {measurements.breadth_mm}mm  "
        f"CI {measurements.cephalic_index}  HC {measurements.circumference_cm}cm"
    )
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.2)

    buf = io.BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def _asymmetry_figure(mesh: trimesh.Trimesh, asymmetry: AsymmetryResult) -> bytes:
    """frontal view (x horizontal, y vertical - see registration.rigid, the
    face-target frame puts x as left/right and y as up/down) of the
    asymmetry heatmap, same blue(dent)/white/red(protruded) diverging scale
    as the live viewer, with an mm colorbar and the single biggest dent and
    biggest protrusion each marked and labeled - "largest regions" here
    just means the two most extreme vertices, not a cluster/region
    detection pass, which felt like more machinery than a quick visual
    reference actually needs."""
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    heatmap = asymmetry.heatmap
    max_abs = max(float(np.abs(heatmap).max()), 1e-6)

    fig = Figure(figsize=(6, 6), dpi=150)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    triangulation = Triangulation(vertices[:, 0], vertices[:, 1], faces)
    mesh_plot = ax.tripcolor(triangulation, heatmap, cmap="bwr", vmin=-max_abs, vmax=max_abs, shading="gouraud")

    dent_idx = int(np.argmin(heatmap))
    protrusion_idx = int(np.argmax(heatmap))
    x_mid = (vertices[:, 0].min() + vertices[:, 0].max()) / 2
    for idx, label in ((dent_idx, "max dent"), (protrusion_idx, "max protrusion")):
        x, y = vertices[idx, 0], vertices[idx, 1]
        ax.plot(x, y, marker="o", markersize=7, markerfacecolor="none", markeredgecolor="black", markeredgewidth=1.5)
        # labels default to the point's upper-right, but the asymmetry data
        # only ever occupies one half of the plot (see the module docstring
        # on why the heatmap is zeroed on the other half) right up against
        # the colorbar - flip to upper-left once a point's already past the
        # midline so the label box doesn't run into it.
        on_right = x > x_mid
        ax.annotate(
            f"{label}\n{heatmap[idx]:+.1f}mm", (x, y),
            textcoords="offset points", xytext=(-8 if on_right else 8, 8),
            ha="right" if on_right else "left", fontsize=7,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8, "linewidth": 0},
        )

    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title(f"facial asymmetry - mean asymmetry index {asymmetry.mean_asymmetry_index:.2f}")
    fig.colorbar(mesh_plot, ax=ax, label="deviation from mirrored half (mm)")

    buf = io.BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def _build_report_files(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    nasion_mesh: trimesh.Trimesh | None = None,
    nasion_landmarks: np.ndarray | None = None,
) -> tuple[str, dict[str, bytes]]:
    """(folder_name, {filename: bytes}) - the same 4 files either delivery
    method writes, named {stem}_registered.ply / _final.ply / _report.json /
    _measurements.png (cranium target only).

    nasion_mesh/nasion_landmarks are only given for a cranial analysis that
    used an alt_frontal_landmark (see pipeline.analyze_cranial) - final_mesh
    and landmarks are the ALT frame in that case (that's deliberately what
    gets exported as the actual mesh - see the docstring on analyze_cranial
    for why), but the saved 2D figure still has to be built from the
    nasion-frame mesh, unconditionally: it's a static picture, so it can't
    "rotate with the viewer" as the display frame does, and craniometrics
    was computed against nasion in the first place. left None (the default),
    this is just final_mesh/landmarks again - the ordinary single-frame case."""
    stem = stem_from_filename(original_filename)
    # cranial and facial analyses of the same source mesh used to collide on
    # one folder name, so the second save silently overwrote the first -
    # the target's initial disambiguates them.
    target_suffix = "C" if target == "cranium" else "F"
    folder = f"CP_{stem}_{target_suffix}_results"

    figure_mesh = nasion_mesh if nasion_mesh is not None else final_mesh
    report_landmarks = nasion_landmarks if nasion_landmarks is not None else landmarks

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_file": original_filename,
        "target": target,
        # always the landmarks craniometrics was actually computed from
        # (nasion, always - see analyze_cranial) - NOT necessarily the
        # frame the exported mesh below is in.
        "landmarks": {
            "nasion": report_landmarks[0].tolist(),
            "left_tragus": report_landmarks[1].tolist(),
            "right_tragus": report_landmarks[2].tolist(),
        },
        "settings": config,
    }
    if nasion_landmarks is not None:
        # the exported mesh's own frame, only present when it differs from
        # the nasion one above
        report["display_frontal_landmark"] = landmarks[0].tolist()
    if craniometrics is not None:
        report["craniometrics"] = {
            "depth_mm": craniometrics.depth_mm,
            "breadth_mm": craniometrics.breadth_mm,
            "cephalic_index": craniometrics.cephalic_index,
            "circumference_cm": craniometrics.circumference_cm,
            "mesh_volume_cc": float(craniometrics.mesh_volume_cc),
            "slice_height": craniometrics.slice_height,
        }
    if asymmetry is not None:
        report["asymmetry"] = {"mean_asymmetry_index": asymmetry.mean_asymmetry_index}

    # bare geometry only, no visual/UV - registered_mesh still carries
    # texture data at this point (register() deliberately keeps it, for the
    # live viewer), but trimesh's PLY writer stores UV as double-precision
    # while vertex positions stay float, and doesn't emit a "TextureFile"
    # comment pointing at the actual image - so the UV ends up orphaned data
    # with no texture ever actually resolvable from the file, and the mixed
    # float/double vertex record is exactly what made Meshmixer read the
    # file as empty (final_mesh never has this problem: repair_mesh already
    # strips visual data before repair runs, further up the pipeline).
    registered_export = trimesh.Trimesh(
        vertices=registered_mesh.vertices, faces=registered_mesh.faces, process=False
    )
    files = {
        f"{stem}_registered.ply": registered_export.export(file_type="ply"),
        f"{stem}_final.ply": final_mesh.export(file_type="ply"),
        f"{stem}_report.json": json.dumps(report, indent=2).encode("utf-8"),
    }
    if craniometrics is not None:
        files[f"{stem}_measurements.png"] = _measurement_figure(figure_mesh, craniometrics)
    if asymmetry is not None:
        files[f"{stem}_asymmetry.png"] = _asymmetry_figure(final_mesh, asymmetry)

    return folder, files


def build_results_bundle(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    nasion_mesh: trimesh.Trimesh | None = None,
    nasion_landmarks: np.ndarray | None = None,
) -> bytes:
    """zip bytes for CP_{stem}_results/ - the browser-download path."""
    folder, files = _build_report_files(
        original_filename, registered_mesh, final_mesh, landmarks, target, craniometrics, asymmetry, config,
        nasion_mesh, nasion_landmarks,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(f"{folder}/{name}", content)
    return buf.getvalue()


def write_results_to_folder(
    dest_dir: Path,
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    nasion_mesh: trimesh.Trimesh | None = None,
    nasion_landmarks: np.ndarray | None = None,
) -> Path:
    """writes CP_{stem}_results/ straight into dest_dir - the desktop app's
    "save next to the original mesh" path, no zip/download step needed since
    we already know a real folder to put it in. returns the folder written."""
    folder, files = _build_report_files(
        original_filename, registered_mesh, final_mesh, landmarks, target, craniometrics, asymmetry, config,
        nasion_mesh, nasion_landmarks,
    )
    results_dir = dest_dir / folder
    results_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (results_dir / name).write_bytes(content)
    return results_dir
