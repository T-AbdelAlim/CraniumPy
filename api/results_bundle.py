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


def _build_report_files(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
) -> tuple[str, dict[str, bytes]]:
    """(folder_name, {filename: bytes}) - the same 4 files either delivery
    method writes, named {stem}_registered.ply / _final.ply / _report.json /
    _measurements.png (cranium target only)."""
    stem = stem_from_filename(original_filename)
    # cranial and facial analyses of the same source mesh used to collide on
    # one folder name, so the second save silently overwrote the first -
    # the target's initial disambiguates them.
    target_suffix = "C" if target == "cranium" else "F"
    folder = f"CP_{stem}_{target_suffix}_results"

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_file": original_filename,
        "target": target,
        "landmarks": {
            "nasion": landmarks[0].tolist(),
            "left_tragus": landmarks[1].tolist(),
            "right_tragus": landmarks[2].tolist(),
        },
        "settings": config,
    }
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

    files = {
        f"{stem}_registered.ply": registered_mesh.export(file_type="ply"),
        f"{stem}_final.ply": final_mesh.export(file_type="ply"),
        f"{stem}_report.json": json.dumps(report, indent=2).encode("utf-8"),
    }
    if craniometrics is not None:
        files[f"{stem}_measurements.png"] = _measurement_figure(final_mesh, craniometrics)

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
) -> bytes:
    """zip bytes for CP_{stem}_results/ - the browser-download path."""
    folder, files = _build_report_files(
        original_filename, registered_mesh, final_mesh, landmarks, target, craniometrics, asymmetry, config
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
) -> Path:
    """writes CP_{stem}_results/ straight into dest_dir - the desktop app's
    "save next to the original mesh" path, no zip/download step needed since
    we already know a real folder to put it in. returns the folder written."""
    folder, files = _build_report_files(
        original_filename, registered_mesh, final_mesh, landmarks, target, craniometrics, asymmetry, config
    )
    results_dir = dest_dir / folder
    results_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (results_dir / name).write_bytes(content)
    return results_dir
