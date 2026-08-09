"""builds the results zip you can download - meshes, a json report, and a
measurement figure, packaged as CP_{filename}_results/. this is basically the
same stuff the old app wrote next to your file (_rg.ply, _metrics.json etc)
just bundled into one download instead of a pile of sibling files.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import numpy as np
import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from craniumpy_core.craniometrics import CranioMeasurements, hc_slice_polygon
from craniumpy_core.asymmetry import AsymmetryResult


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
    """zip bytes for CP_{stem}_results/, containing:
    - {stem}_registered.ply - mesh right after registration, before clip/repair/resample
    - {stem}_final.ply - mesh after the whole pipeline, what the measurements ran on
    - {stem}_report.json - measurements + landmarks + whatever settings were used
    - {stem}_measurements.png - the HC-slice figure (cranium target only)
    """
    stem = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
    folder = f"CP_{stem}_results"

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

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/{stem}_registered.ply", registered_mesh.export(file_type="ply"))
        zf.writestr(f"{folder}/{stem}_final.ply", final_mesh.export(file_type="ply"))
        zf.writestr(f"{folder}/{stem}_report.json", json.dumps(report, indent=2))
        if craniometrics is not None:
            zf.writestr(f"{folder}/{stem}_measurements.png", _measurement_figure(final_mesh, craniometrics))

    return buf.getvalue()
