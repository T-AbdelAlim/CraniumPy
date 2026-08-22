"""unit tests for src/craniumpy_core/cohort.py - pure function tests, no
FastAPI needed, same style as test_reporting.py testing the underlying
math/IO directly. api/routers/cohort.py's own request/response plumbing is
covered separately in test_api.py."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import trimesh
from openpyxl import Workbook

from craniumpy_core.cohort import (
    hc_ring_band,
    load_cohort_xlsx,
    load_demo_cohort,
    mean_shape,
    mean_shape_with_outliers,
    measure_mean_shape,
    metopic_band,
    reference_diff,
    sagittal_midline_band,
)


# --- load_cohort_xlsx ---------------------------------------------------


def _write_xlsx(path_or_buffer, header: list[str], rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path_or_buffer)


def test_load_cohort_xlsx_round_trips_from_a_real_path(tmp_path):
    path = tmp_path / "cohort.xlsx"
    _write_xlsx(path, ["patient_id", "age_imaging", "diagnosis"], [["P001", 12, "metopic"], ["P002", 7, "control"]])

    columns, rows = load_cohort_xlsx(path)

    assert columns == ["patient_id", "age_imaging", "diagnosis"]
    assert rows == [
        {"patient_id": "P001", "age_imaging": "12", "diagnosis": "metopic"},
        {"patient_id": "P002", "age_imaging": "7", "diagnosis": "control"},
    ]


def test_load_cohort_xlsx_accepts_an_in_memory_buffer():
    buffer = io.BytesIO()
    _write_xlsx(buffer, ["patient_id"], [["P001"]])
    buffer.seek(0)

    columns, rows = load_cohort_xlsx(buffer)

    assert columns == ["patient_id"]
    assert rows == [{"patient_id": "P001"}]


def test_load_cohort_xlsx_blank_cells_come_through_as_empty_string_not_omitted(tmp_path):
    path = tmp_path / "cohort.xlsx"
    _write_xlsx(path, ["patient_id", "cephalic_index"], [["P001", None]])

    _columns, rows = load_cohort_xlsx(path)

    assert rows[0]["cephalic_index"] == ""


def test_load_cohort_xlsx_skips_entirely_blank_trailing_rows(tmp_path):
    path = tmp_path / "cohort.xlsx"
    _write_xlsx(path, ["patient_id"], [["P001"], [None]])

    _columns, rows = load_cohort_xlsx(path)

    assert len(rows) == 1


# --- mean_shape ----------------------------------------------------------


def _tetrahedron(offset: np.ndarray) -> trimesh.Trimesh:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    ) + offset
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _write_mesh(mesh: trimesh.Trimesh, path: Path) -> Path:
    mesh.export(path)
    return path


def test_mean_shape_of_identical_meshes_has_zero_variability(tmp_path):
    paths = [_write_mesh(_tetrahedron(np.zeros(3)), tmp_path / f"m{i}.ply") for i in range(3)]

    result = mean_shape(paths)

    assert result.source_count == 3
    assert len(result.mesh.vertices) == 4
    assert np.allclose(result.variability, 0.0)
    assert np.allclose(np.asarray(result.mesh.vertices), _tetrahedron(np.zeros(3)).vertices)


def test_mean_shape_averages_vertex_positions_and_reports_spread(tmp_path):
    paths = [
        _write_mesh(_tetrahedron(np.array([-1.0, 0.0, 0.0])), tmp_path / "m0.ply"),
        _write_mesh(_tetrahedron(np.array([1.0, 0.0, 0.0])), tmp_path / "m1.ply"),
    ]

    result = mean_shape(paths)

    assert np.allclose(np.asarray(result.mesh.vertices), _tetrahedron(np.zeros(3)).vertices)
    # each vertex sits 1.0 away from the mean on both inputs, symmetrically
    assert np.allclose(result.variability, 1.0)


def test_mean_shape_rejects_mismatched_vertex_counts(tmp_path):
    good = _write_mesh(_tetrahedron(np.zeros(3)), tmp_path / "good.ply")
    box = _write_mesh(trimesh.creation.box(), tmp_path / "box.ply")

    with pytest.raises(ValueError, match="vertices"):
        mean_shape([good, box])


def test_mean_shape_rejects_mismatched_face_connectivity(tmp_path):
    a = _tetrahedron(np.zeros(3))
    b = trimesh.Trimesh(
        vertices=a.vertices,
        faces=np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [2, 1, 3]]),
        process=False,
    )
    path_a = _write_mesh(a, tmp_path / "a.ply")
    path_b = _write_mesh(b, tmp_path / "b.ply")

    with pytest.raises(ValueError, match="face connectivity"):
        mean_shape([path_a, path_b])


def test_mean_shape_rejects_empty_input():
    with pytest.raises(ValueError):
        mean_shape([])


# --- mean_shape_with_outliers ----------------------------------------------


def test_mean_shape_with_outliers_averages_the_majority_and_excludes_the_rest(tmp_path):
    # 3 good tetrahedra (majority) + 1 mismatched-vertex-count box + 1
    # mismatched-face-connectivity tetrahedron - the majority group should
    # be averaged, the other two excluded with distinct reasons.
    good_paths = [
        _write_mesh(_tetrahedron(np.array([float(i), 0.0, 0.0])), tmp_path / f"good{i}.ply") for i in range(3)
    ]
    box_path = _write_mesh(trimesh.creation.box(), tmp_path / "box.ply")
    bad_faces = trimesh.Trimesh(
        vertices=_tetrahedron(np.zeros(3)).vertices,
        faces=np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [2, 1, 3]]),
        process=False,
    )
    bad_faces_path = _write_mesh(bad_faces, tmp_path / "bad_faces.ply")

    result, excluded = mean_shape_with_outliers([*good_paths, box_path, bad_faces_path])

    assert result.source_count == 3
    assert len(result.mesh.vertices) == 4
    excluded_by_path = {e.path: e.reason for e in excluded}
    assert str(box_path) in excluded_by_path
    assert "vertices" in excluded_by_path[str(box_path)]
    assert str(bad_faces_path) in excluded_by_path
    assert "face connectivity" in excluded_by_path[str(bad_faces_path)]


def test_mean_shape_with_outliers_excludes_a_file_that_fails_to_load(tmp_path):
    good_paths = [
        _write_mesh(_tetrahedron(np.array([float(i), 0.0, 0.0])), tmp_path / f"good{i}.ply") for i in range(2)
    ]
    corrupt_path = tmp_path / "corrupt.ply"
    corrupt_path.write_text("not a real mesh file")

    result, excluded = mean_shape_with_outliers([*good_paths, corrupt_path])

    assert result.source_count == 2
    assert len(excluded) == 1
    assert excluded[0].path == str(corrupt_path)
    assert "could not load" in excluded[0].reason


def test_mean_shape_with_outliers_of_identical_meshes_excludes_nothing(tmp_path):
    paths = [_write_mesh(_tetrahedron(np.zeros(3)), tmp_path / f"m{i}.ply") for i in range(3)]

    result, excluded = mean_shape_with_outliers(paths)

    assert result.source_count == 3
    assert excluded == []


def test_mean_shape_with_outliers_rejects_empty_input():
    with pytest.raises(ValueError):
        mean_shape_with_outliers([])


def test_mean_shape_with_outliers_rejects_when_nothing_could_be_averaged(tmp_path):
    corrupt_path = tmp_path / "corrupt.ply"
    corrupt_path.write_text("not a real mesh file")

    with pytest.raises(ValueError, match="no mesh could be loaded"):
        mean_shape_with_outliers([corrupt_path])


# --- reference_diff -------------------------------------------------------


def test_reference_diff_recovers_a_known_outward_displacement():
    # move every reference vertex outward along the reference's OWN vertex
    # normal by a known constant k - reference_diff should then recover
    # exactly k everywhere (dot(k * unit_normal, unit_normal) == k), giving
    # an exact assertion instead of just a sign check.
    reference = trimesh.creation.icosphere(subdivisions=1)
    normals = np.asarray(reference.vertex_normals)
    k = 1.5
    mean_vertices = np.asarray(reference.vertices) + k * normals
    mean_mesh = trimesh.Trimesh(vertices=mean_vertices, faces=reference.faces, process=False)

    diff = reference_diff(mean_mesh, reference)

    assert np.allclose(diff, k, atol=1e-6)


def test_reference_diff_recovers_a_known_inward_displacement():
    reference = trimesh.creation.icosphere(subdivisions=1)
    normals = np.asarray(reference.vertex_normals)
    k = -0.8
    mean_vertices = np.asarray(reference.vertices) + k * normals
    mean_mesh = trimesh.Trimesh(vertices=mean_vertices, faces=reference.faces, process=False)

    diff = reference_diff(mean_mesh, reference)

    assert np.allclose(diff, k, atol=1e-6)


def test_reference_diff_rejects_mismatched_topology():
    reference = trimesh.creation.icosphere(subdivisions=1)
    other = trimesh.creation.box()

    with pytest.raises(ValueError, match="vertices"):
        reference_diff(other, reference)


# --- measure_mean_shape ----------------------------------------------------
# exercises real demo-cohort mean shapes (see load_demo_cohort) rather than
# a synthetic fixture - this needs real head-shaped geometry (a slice
# search, a forehead contour) that a tetrahedron/box can't stand in for.


def _demo_mean_mesh(template_name):
    _columns, rows = load_demo_cohort()
    paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == template_name]
    return mean_shape(paths).mesh


def test_measure_mean_shape_cranium_target_computes_craniometrics_and_asymmetry():
    mesh = _demo_mean_mesh("clipped_template_xy_com")

    result = measure_mean_shape(mesh, "cranium")

    assert result.craniometrics is not None
    assert result.craniometrics.cephalic_index > 0
    assert result.craniometrics.depth_mm > 0
    assert result.metopic is None
    assert result.asymmetry.mean_asymmetry_index >= 0
    assert result.frontal_bossing is not None


def test_measure_mean_shape_face_target_computes_metopic_and_asymmetry():
    mesh = _demo_mean_mesh("template_face")

    result = measure_mean_shape(mesh, "face")

    assert result.metopic is not None
    assert result.craniometrics is None
    assert result.asymmetry.mean_asymmetry_index >= 0
    assert np.isfinite(result.slice_height)


# --- sagittal_midline_band --------------------------------------------------
# same "exercise the real demo-cohort meshes" reasoning as
# test_measure_mean_shape_* above - this needs real head-shaped geometry
# (a sagittal section, a forehead-vs-occiput split) a synthetic primitive
# can't stand in for.


def test_sagittal_midline_band_cranium_target():
    _columns, rows = load_demo_cohort()
    paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == "clipped_template_xy_com"]

    band = sagittal_midline_band(paths, "cranium")

    assert band.source_count == len(paths)
    assert len(band.y) == len(band.mean_z) == len(band.sd_z) == 60
    assert np.all(np.diff(band.y) > 0)  # strictly ascending height grid
    assert np.all(band.sd_z >= 0)
    assert np.all(np.isfinite(band.mean_z))
    # a group of real (if synthetic) head shapes shouldn't disagree by
    # tens of millimetres at a shared height - this is the regression this
    # function's own _select_forehead_half step exists to prevent (see its
    # docstring): without it, forehead points get averaged against
    # occipital ones and the spread blows up to that scale.
    assert band.sd_z.max() < 20.0


def test_sagittal_midline_band_face_target():
    _columns, rows = load_demo_cohort()
    paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == "template_face"]

    band = sagittal_midline_band(paths, "face")

    assert band.source_count == len(paths)
    assert np.all(band.sd_z >= 0)
    assert band.sd_z.max() < 20.0


def test_sagittal_midline_band_rejects_mismatched_topology(tmp_path):
    a = _write_mesh(_tetrahedron(np.zeros(3)), tmp_path / "a.ply")
    b = _write_mesh(trimesh.creation.box(), tmp_path / "b.ply")

    with pytest.raises(ValueError):
        sagittal_midline_band([a, b], "cranium")


def test_sagittal_midline_band_rejects_empty_input():
    with pytest.raises(ValueError):
        sagittal_midline_band([], "cranium")


# --- hc_ring_band -------------------------------------------------------


def test_hc_ring_band_cranium_target():
    _columns, rows = load_demo_cohort()
    paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == "clipped_template_xy_com"]

    band = hc_ring_band(paths, "cranium")

    assert band.source_count == len(paths)
    assert band.closed is True
    assert band.mean.shape == band.inner.shape == band.outer.shape == (72, 3)
    assert np.all(np.isfinite(band.mean))
    # inner/outer should straddle mean at a consistent (small, real-head-scale)
    # distance - not identical to mean (zero spread) and not wildly larger
    # than a real skull's own radius.
    spread = np.linalg.norm(band.outer - band.inner, axis=1)
    assert np.all(spread > 0)
    assert spread.max() < 20.0


def test_hc_ring_band_rejects_mismatched_topology(tmp_path):
    a = _write_mesh(_tetrahedron(np.zeros(3)), tmp_path / "a.ply")
    b = _write_mesh(trimesh.creation.box(), tmp_path / "b.ply")

    with pytest.raises(ValueError):
        hc_ring_band([a, b], "cranium")


def test_hc_ring_band_rejects_empty_input():
    with pytest.raises(ValueError):
        hc_ring_band([], "cranium")


# --- metopic_band ---------------------------------------------------------


def test_metopic_band_face_target():
    _columns, rows = load_demo_cohort()
    paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == "template_face"]

    band = metopic_band(paths, "face")

    assert band.source_count == len(paths)
    assert band.closed is False
    n = band.mean.shape[0]
    assert band.inner.shape == band.outer.shape == (n, 3)
    assert np.all(np.isfinite(band.mean))
    spread = np.linalg.norm(band.outer - band.inner, axis=1)
    assert np.all(spread > 0)
    assert spread.max() < 20.0


def test_metopic_band_rejects_mismatched_topology(tmp_path):
    a = _write_mesh(_tetrahedron(np.zeros(3)), tmp_path / "a.ply")
    b = _write_mesh(trimesh.creation.box(), tmp_path / "b.ply")

    with pytest.raises(ValueError):
        metopic_band([a, b], "face")


def test_metopic_band_rejects_empty_input():
    with pytest.raises(ValueError):
        metopic_band([], "face")


# --- load_demo_cohort -----------------------------------------------------
# exercises the shipped demo asset itself (see scripts/generate_demo_cohort.py)
# rather than a synthetic fixture - this is what actually ships, so a stale/
# missing asset should fail these tests, not just the demo endpoint at runtime.


def test_load_demo_cohort_resolves_relative_mesh_paths_to_real_files():
    columns, rows = load_demo_cohort()
    assert "nicp_mesh_path" in columns
    assert len(rows) > 0

    nicp_rows = [r for r in rows if r["nicp_used"] == "yes"]
    assert len(nicp_rows) > 0
    for row in nicp_rows:
        mesh_path = Path(row["nicp_mesh_path"])
        assert mesh_path.is_absolute()
        assert mesh_path.is_file()

    non_nicp_rows = [r for r in rows if r["nicp_used"] != "yes"]
    assert all(r["nicp_mesh_path"] == "" for r in non_nicp_rows)


def test_load_demo_cohort_meshes_are_averageable_within_a_template_group():
    _columns, rows = load_demo_cohort()
    templates = {r["nicp_template"] for r in rows if r["nicp_used"] == "yes"}
    assert len(templates) >= 1

    for template in templates:
        paths = [Path(r["nicp_mesh_path"]) for r in rows if r["nicp_template"] == template]
        assert len(paths) >= 2
        result = mean_shape(paths)
        assert result.source_count == len(paths)
