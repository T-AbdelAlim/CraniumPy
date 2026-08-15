"""builds the results you get after an analysis - meshes, a json report, and
a measurement figure, packaged as CP_{stem}_{C|F}_{3|4}[_CoM]/ (see
results_folder_name). this is basically the same stuff the old app wrote
next to your file (_rg.ply, _metrics.json etc), just organized into one
folder now instead of a pile of sibling files.

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
from craniumpy_core.remesh import _boundary_loops


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


def results_folder_name(original_filename: str, target: str, config: dict) -> str:
    """CP_{stem}_{C|F}_{3|4}[_CoM] - what actually went into this run, not
    a generic "_results" suffix: landmark count (4 when an
    alt_frontal_landmark was given, see pipeline.analyze_cranial) and
    whether center-of-mass correction ran. two runs with different
    settings on the same file land in different folders instead of one
    overwriting the other, and the name tells you which is which without
    opening report.json."""
    stem = stem_from_filename(original_filename)
    target_suffix = "C" if target == "cranium" else "F"
    landmark_count = 4 if config.get("alt_frontal_landmark") else 3
    com_suffix = "_CoM" if config.get("com_translation") else ""
    return f"CP_{stem}_{target_suffix}_{landmark_count}{com_suffix}"


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
    as the live viewer, with an mm colorbar."""
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    heatmap = asymmetry.heatmap
    max_abs = max(float(np.abs(heatmap).max()), 1e-6)

    fig = Figure(figsize=(6, 6), dpi=150)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    triangulation = Triangulation(vertices[:, 0], vertices[:, 1], faces)
    mesh_plot = ax.tripcolor(triangulation, heatmap, cmap="bwr", vmin=-max_abs, vmax=max_abs, shading="gouraud")

    # the heatmap is only ever non-zero on one half (see module docstring) -
    # 0.0 on this diverging colormap renders as pure white, indistinguishable
    # from the plot background, so the other half reads as simply missing.
    # the mesh's own clip-boundary loop is already roughly face-shaped (facial
    # clipping crops around the face), so trace it as a light silhouette to
    # keep the whole face visible regardless of which half has data.
    for loop in _boundary_loops(mesh):
        loop_xy = vertices[np.append(loop, loop[0])][:, :2]
        ax.plot(loop_xy[:, 0], loop_xy[:, 1], color="#999999", linewidth=0.8, zorder=3)

    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title(f"facial asymmetry - mean asymmetry index {asymmetry.mean_asymmetry_index:.2f}")
    fig.colorbar(mesh_plot, ax=ax, label="deviation from mirrored half (mm)")

    buf = io.BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def _build_mesh_files(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    target: str,
    config: dict,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> tuple[str, dict[str, bytes]]:
    """(folder_name, {filename: bytes}) - the two mesh files, {stem}_rg.ply
    / _rg_{C|F}.ply, plus a third _rg_{C|F}N.ply when nicp_mesh is given -
    the topology-consistent template fit ("fit template" in the UI), kept
    alongside the patient's own clipped/resampled mesh rather than in place
    of it. {C|F} is cranial/facial, same convention as results_folder_name."""
    stem = stem_from_filename(original_filename)
    folder = results_folder_name(original_filename, target, config)

    # bare geometry only, no visual/UV - registered_mesh still carries
    # texture data at this point (register() deliberately keeps it, for the
    # live viewer), but trimesh's PLY writer stores UV as double-precision
    # while vertex positions stay float, and never writes a "TextureFile"
    # comment pointing at the actual image - so the UV is orphaned data with
    # no texture resolvable from the file, and the mixed float/double
    # vertex record makes some tools (Meshmixer) read the file as empty.
    # final_mesh never has this problem since repair_mesh already strips
    # visual data before repair runs, further up the pipeline.
    registered_export = trimesh.Trimesh(
        vertices=registered_mesh.vertices, faces=registered_mesh.faces, process=False
    )
    target_suffix = "C" if target == "cranium" else "F"
    files = {
        f"{stem}_rg.ply": registered_export.export(file_type="ply"),
        f"{stem}_rg_{target_suffix}.ply": final_mesh.export(file_type="ply"),
    }
    if nicp_mesh is not None:
        files[f"{stem}_rg_{target_suffix}N.ply"] = nicp_mesh.export(file_type="ply")
    return folder, files


def _build_analysis_files(
    original_filename: str,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    sellion_mesh: trimesh.Trimesh | None = None,
    sellion_landmarks: np.ndarray | None = None,
) -> dict[str, bytes]:
    """{filename: bytes} - {stem}_report.json / _measurements.png (cranium
    target only) / _asymmetry.png (face target only).

    sellion_mesh/sellion_landmarks are only given for a cranial analysis that
    used an alt_frontal_landmark - final_mesh and landmarks are the ALT
    frame in that case (deliberately, that's what gets exported as the
    mesh - see analyze_cranial), but the saved 2D figure still has to come
    from the sellion-frame mesh: it's a static picture, so it can't "rotate
    with the viewer" the way the display frame does, and craniometrics was
    computed against sellion in the first place. left None (the default),
    this is just final_mesh/landmarks again - the ordinary single-frame
    case."""
    stem = stem_from_filename(original_filename)
    figure_mesh = sellion_mesh if sellion_mesh is not None else final_mesh
    report_landmarks = sellion_landmarks if sellion_landmarks is not None else landmarks

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_file": original_filename,
        "target": target,
        # always the landmarks craniometrics was actually computed from
        # (sellion, always - see analyze_cranial) - NOT necessarily the
        # frame the exported mesh is in.
        "landmarks": {
            "sellion": report_landmarks[0].tolist(),
            "left_tragus": report_landmarks[1].tolist(),
            "right_tragus": report_landmarks[2].tolist(),
        },
        "settings": config,
    }
    if sellion_landmarks is not None:
        # the exported mesh's own frame, only present when it differs from
        # the sellion one above
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

    files = {f"{stem}_report.json": json.dumps(report, indent=2).encode("utf-8")}
    if craniometrics is not None:
        files[f"{stem}_measurements.png"] = _measurement_figure(figure_mesh, craniometrics)
    if asymmetry is not None:
        files[f"{stem}_asymmetry.png"] = _asymmetry_figure(final_mesh, asymmetry)
    return files


def _zip_files(files_by_prefix: dict[str, dict[str, bytes]]) -> bytes:
    """{zip-path-prefix: {filename: bytes}} -> zip bytes - shared by every
    zip-producing function below, so meshes-only/analysis-only/combined
    bundles all build the same way."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for prefix, files in files_by_prefix.items():
            for name, content in files.items():
                zf.writestr(f"{prefix}/{name}" if prefix else name, content)
    return buf.getvalue()


def build_meshes_bundle(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    target: str,
    config: dict,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> bytes:
    """zip bytes for the mesh files (two, or three when a NICP fit exists -
    see _build_mesh_files) - the browser-download side of "save meshes"
    (part 9)."""
    folder, files = _build_mesh_files(original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)
    return _zip_files({folder: files})


def write_meshes_to_folder(
    dest_dir: Path,
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    target: str,
    config: dict,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> Path:
    """writes the mesh files (two, or three when a NICP fit exists) straight
    into dest_dir/{folder} - the desktop side of "save meshes" (part 9).
    returns the folder written."""
    folder, files = _build_mesh_files(original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)
    results_dir = dest_dir / folder
    results_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (results_dir / name).write_bytes(content)
    return results_dir


def build_analysis_bundle(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    sellion_mesh: trimesh.Trimesh | None = None,
    sellion_landmarks: np.ndarray | None = None,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> bytes:
    """zip bytes for the mesh files (two, or three - see _build_mesh_files)
    plus a nested analysis/ subfolder - the browser-download side of
    "export analysis" (part 10). self-contained (always includes the
    meshes) since there's no persistent folder to add an analysis/
    subfolder onto across separate browser downloads, unlike
    write_analysis_to_folder below."""
    folder, mesh_files = _build_mesh_files(original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)
    analysis_files = _build_analysis_files(
        original_filename, final_mesh, landmarks, target, craniometrics, asymmetry, config, sellion_mesh, sellion_landmarks
    )
    return _zip_files({folder: mesh_files, f"{folder}/analysis": analysis_files})


def write_analysis_to_folder(
    dest_dir: Path,
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    sellion_mesh: trimesh.Trimesh | None = None,
    sellion_landmarks: np.ndarray | None = None,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> Path:
    """writes the report/figures into dest_dir/{folder}/analysis/ - the
    desktop side of "export analysis" (part 10). if the mesh folder doesn't
    exist yet (meshes were never separately saved), writes those first -
    see write_meshes_to_folder. returns the analysis folder written."""
    folder_name = results_folder_name(original_filename, target, config)
    results_dir = dest_dir / folder_name
    if not results_dir.exists():
        write_meshes_to_folder(dest_dir, original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)

    analysis_dir = results_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    files = _build_analysis_files(
        original_filename, final_mesh, landmarks, target, craniometrics, asymmetry, config, sellion_mesh, sellion_landmarks
    )
    for name, content in files.items():
        (analysis_dir / name).write_bytes(content)
    return analysis_dir


def build_results_bundle(
    original_filename: str,
    registered_mesh: trimesh.Trimesh,
    final_mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    target: str,
    craniometrics: CranioMeasurements | None,
    asymmetry: AsymmetryResult | None,
    config: dict,
    sellion_mesh: trimesh.Trimesh | None = None,
    sellion_landmarks: np.ndarray | None = None,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> bytes:
    """zip bytes for the results folder (see results_folder_name), meshes
    (two, or three - see _build_mesh_files) and analysis flat together -
    the original "everything in one shot" browser-download path (pre-dates
    the separate save-meshes/export-analysis split - part 9/10 - and keeps
    its existing flat layout for backward compatibility rather than
    adopting their nested analysis/ convention)."""
    folder, mesh_files = _build_mesh_files(original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)
    analysis_files = _build_analysis_files(
        original_filename, final_mesh, landmarks, target, craniometrics, asymmetry, config, sellion_mesh, sellion_landmarks
    )
    return _zip_files({folder: {**mesh_files, **analysis_files}})


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
    sellion_mesh: trimesh.Trimesh | None = None,
    sellion_landmarks: np.ndarray | None = None,
    nicp_mesh: trimesh.Trimesh | None = None,
) -> Path:
    """writes the results folder (see results_folder_name) straight into
    dest_dir, meshes and analysis flat together - the original "everything
    in one shot" desktop-save path (see build_results_bundle for why this
    stays flat rather than nesting analysis/ like part 9/10's split
    functions do)."""
    folder, mesh_files = _build_mesh_files(original_filename, registered_mesh, final_mesh, target, config, nicp_mesh)
    analysis_files = _build_analysis_files(
        original_filename, final_mesh, landmarks, target, craniometrics, asymmetry, config, sellion_mesh, sellion_landmarks
    )
    results_dir = dest_dir / folder
    results_dir.mkdir(parents=True, exist_ok=True)
    for name, content in {**mesh_files, **analysis_files}.items():
        (results_dir / name).write_bytes(content)
    return results_dir
