"""unit tests for the summary-spreadsheet/cohort-spreadsheet pieces of
api/results_bundle.py - pure function tests, no FastAPI/mesh pipeline
needed, same style as test_craniometrics.py/test_metopic.py testing the
underlying math directly.

_report_pdf's own layout isn't covered here beyond the line-advance
arithmetic below - the API-level tests in test_api.py exercise the whole
thing by opening the PDF that comes out of a real export."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from openpyxl import Workbook, load_workbook

from api.results_bundle import _id_mapping_path, _metrics_row, _summary_xlsx, _upsert_cohort_xlsx
from craniumpy_core.asymmetry import AsymmetryResult
from craniumpy_core.craniometrics import CranioMeasurements, FrontalBossingResult
from craniumpy_core.metopic import MetopicResult


def _config(com_translation: bool = True, nicp: dict | None = None) -> dict:
    return {"com_translation": com_translation, "nicp": nicp}


def _craniometrics() -> CranioMeasurements:
    return CranioMeasurements(
        slice_height=10.0,
        depth_mm=59.1234,
        breadth_mm=67.001,
        cephalic_index=113.4,
        circumference_cm=19.7,
        mesh_volume_cc=9.05,
        front_opt=np.zeros(3),
        occ_opt=np.zeros(3),
        lh_opt=np.zeros(3),
        rh_opt=np.zeros(3),
    )


def _asymmetry() -> AsymmetryResult:
    return AsymmetryResult(heatmap=np.zeros(5), mean_asymmetry_index=4.401)


def _frontal_bossing() -> FrontalBossingResult:
    return FrontalBossingResult(
        angle_deg=159.026, sellion=np.zeros(3), frontal_point=np.zeros(3), profile=np.zeros((3, 3))
    )


def _metopic() -> MetopicResult:
    return MetopicResult(
        contour=np.zeros((3, 2)),
        arc_length=np.zeros(3),
        normalized_arc_length=np.zeros(3),
        midline_u=0.5,
        parabola_a=-0.01,
        parabola_c=30.0,
        deviation_profile=np.zeros(3),
        gradient_profile=np.zeros(3),
        curvature_profile=np.zeros(3),
        frontal_angle_deg=120.456,
        frontal_angle_points=(np.zeros(2), np.zeros(2), np.zeros(2)),
        forehead_width_mm=80.0,
        midline_curvature_concentration=0.3,
        midline_max_curvature=0.01,
        midline_max_curvature_position=0.5,
        ridge_protrusion_mm=2.5,
        ridge_protrusion_position=0.5,
        ridge_area_mm2=120.0,
        ridge_area_normalized=0.05,
        left_temporal_hollowing=0.1,
        right_temporal_hollowing=0.05,
        mean_temporal_hollowing=0.075,
        left_max_temporal_depth_mm=1.2,
        right_max_temporal_depth_mm=0.8,
        parabolic_deviation_index=0.9,
        central_window=(0.4, 0.6),
        left_temporal_window=(0.1, 0.3),
        right_temporal_window=(0.7, 0.9),
    )


_METADATA_KEYS = (
    "file_name", "file_path", "patient_id", "sex", "date_imaging", "age_imaging",
    "treatment", "age_surgery_months", "free_variable",
)
_SETTINGS_KEYS = ("com_correction", "nicp_used", "nicp_template")


# --- _metrics_row -----------------------------------------------------


def test_metrics_row_blank_metadata_and_missing_metrics_come_through_empty_not_omitted():
    row = _metrics_row("cranium", {}, _config(com_translation=False), None, None, None, None)

    for key in _METADATA_KEYS:
        assert row[key] == ""
    assert row["target"] == "cranium"
    for key in ("depth_mm", "breadth_mm", "cephalic_index", "circumference_cm", "mesh_volume_cc",
                "mean_asymmetry_index", "frontal_bossing_angle_deg"):
        assert row[key] == ""
    assert all(v == "" for k, v in row.items() if k.startswith("metopic_"))


def test_metrics_row_echoes_metadata_fields_verbatim():
    metadata = {key: f"value-{key}" for key in _METADATA_KEYS}
    row = _metrics_row("face", metadata, _config(), None, None, None, None)
    for key in _METADATA_KEYS:
        assert row[key] == f"value-{key}"


def test_metrics_row_only_populates_applicable_metric_groups():
    # cranial-style session: craniometrics + frontal_bossing present,
    # asymmetry/metopic absent (as a real facial-only pair would be) - the
    # row must still carry every column, just blank for the absent ones.
    row = _metrics_row("cranium", {}, _config(), _craniometrics(), None, None, _frontal_bossing())

    assert row["depth_mm"] == "59.12"
    assert row["breadth_mm"] == "67.00"
    assert row["frontal_bossing_angle_deg"] == "159.03"
    assert row["mean_asymmetry_index"] == ""
    assert all(v == "" for k, v in row.items() if k.startswith("metopic_"))


def test_metrics_row_populates_metopic_and_asymmetry_when_given():
    row = _metrics_row("face", {}, _config(), None, _asymmetry(), _metopic(), None)

    assert row["mean_asymmetry_index"] == "4.40"
    assert row["metopic_frontal_angle_deg"] == "120.46"
    assert row["metopic_ridge_protrusion_mm"] == "2.50"
    assert row["depth_mm"] == ""
    assert row["frontal_bossing_angle_deg"] == ""


def test_metrics_row_settings_reflect_com_and_nicp_off():
    row = _metrics_row("cranium", {}, _config(com_translation=False, nicp=None), None, None, None, None)

    assert row["com_correction"] == "no"
    assert row["nicp_used"] == "no"
    assert row["nicp_template"] == ""


def test_metrics_row_settings_reflect_com_and_nicp_on_with_shipped_template():
    row = _metrics_row(
        "cranium", {}, _config(com_translation=True, nicp={"template": "cranium_com", "custom_template_path": None}),
        None, None, None, None,
    )

    assert row["com_correction"] == "yes"
    assert row["nicp_used"] == "yes"
    assert row["nicp_template"] == "cranium_com"


def test_metrics_row_settings_nicp_template_uses_filename_not_full_path():
    row = _metrics_row(
        "cranium", {},
        _config(nicp={"template": None, "custom_template_path": "/data/templates/my_template.ply"}),
        None, None, None, None,
    )

    assert row["nicp_used"] == "yes"
    assert row["nicp_template"] == "my_template.ply"


# --- _summary_xlsx -------------------------------------------------------


def _read_sheet(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """mirrors what a numeric cell actually displays in Excel (2 decimals,
    per the number_format _write_xlsx_rows applies), not Python's own
    str() - which drops the decimals entirely for a whole number (openpyxl
    hands a whole-valued numeric cell back as int, e.g. 61 not 61.0) or
    drops a trailing zero for a fraction (str(70.5) == "70.5", not
    "70.50") - either way not what a person actually sees in the sheet,
    and not what an exact round-trip comparison against a _fmt(...) string
    like "61.00" should be checked against."""
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb.active
    header = [str(c.value) if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    rows = []
    for excel_row in ws.iter_rows(min_row=2, values_only=True):
        cells = {}
        for i, v in enumerate(excel_row):
            if v is None:
                cells[header[i]] = ""
            elif isinstance(v, (int, float)):
                cells[header[i]] = f"{v:.2f}"
            else:
                cells[header[i]] = str(v)
        rows.append(cells)
    return rows


def test_summary_xlsx_round_trips_the_row():
    row = _metrics_row("cranium", {"file_name": "patient1.ply", "sex": "female"}, _config(), _craniometrics(), None, None, None)
    xlsx_bytes = _summary_xlsx(row)

    wb = load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb.active
    header_cells = list(next(ws.iter_rows(min_row=1, max_row=1)))
    assert [c.value for c in header_cells] == list(row.keys())
    assert header_cells[0].font.bold  # sanity: the header row is styled, not plain text

    rows = _read_sheet(xlsx_bytes)
    assert len(rows) == 1
    assert rows[0] == row


# --- _upsert_cohort_xlsx ---------------------------------------------------


def _read_cohort(path: Path) -> list[dict[str, str]]:
    return _read_sheet(path.read_bytes())


def _read_mapping(cohort_path: Path) -> list[dict[str, str]]:
    return _read_sheet(_id_mapping_path(cohort_path).read_bytes())


def test_upsert_cohort_xlsx_creates_file_with_header_and_row(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    row = _metrics_row(
        "cranium", {"file_name": "a.ply", "file_path": "/data/a.ply", "patient_id": "MRN-1"},
        _config(), _craniometrics(), None, None, None,
    )

    _upsert_cohort_xlsx(cohort_path, row)

    assert cohort_path.exists()
    rows = _read_cohort(cohort_path)
    assert len(rows) == 1
    # the shared cohort file gets a cohort_id in place of the local
    # patient_id - see test_upsert_cohort_xlsx_writes_local_id_mapping_file
    # for where patient_id actually ends up
    assert rows[0]["cohort_id"] == "C00001"
    assert "patient_id" not in rows[0]
    assert rows[0]["file_path"] == "/data/a.ply"
    assert rows[0]["depth_mm"] == row["depth_mm"]


def test_upsert_cohort_xlsx_writes_local_id_mapping_file(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    row = _metrics_row(
        "cranium", {"file_name": "a.ply", "file_path": "/data/a.ply", "patient_id": "MRN-1"},
        _config(), _craniometrics(), None, None, None,
    )

    _upsert_cohort_xlsx(cohort_path, row)

    mapping_path = _id_mapping_path(cohort_path)
    assert mapping_path.exists()
    assert mapping_path != cohort_path
    mapping_rows = _read_mapping(cohort_path)
    assert len(mapping_rows) == 1
    assert mapping_rows[0]["cohort_id"] == "C00001"
    assert mapping_rows[0]["patient_id"] == "MRN-1"
    assert mapping_rows[0]["file_path"] == "/data/a.ply"


def test_upsert_cohort_xlsx_appends_a_genuinely_new_row(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    row_a = _metrics_row("cranium", {"file_name": "a.ply", "file_path": "/data/a.ply"}, _config(), _craniometrics(), None, None, None)
    row_b = _metrics_row("face", {"file_name": "b.ply", "file_path": "/data/b.ply"}, _config(), None, _asymmetry(), None, None)

    _upsert_cohort_xlsx(cohort_path, row_a)
    _upsert_cohort_xlsx(cohort_path, row_b)

    rows = _read_cohort(cohort_path)
    assert len(rows) == 2
    assert rows[0]["file_path"] == "/data/a.ply"
    assert rows[1]["file_path"] == "/data/b.ply"
    # each distinct file gets its own, sequential cohort_id
    assert rows[0]["cohort_id"] == "C00001"
    assert rows[1]["cohort_id"] == "C00002"


def test_upsert_cohort_xlsx_replaces_row_with_matching_file_path_instead_of_duplicating(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    first = _metrics_row("cranium", {"file_name": "a.ply", "file_path": "/data/a.ply"}, _config(), _craniometrics(), None, None, None)
    _upsert_cohort_xlsx(cohort_path, first)

    updated_craniometrics = _craniometrics()
    updated_craniometrics.depth_mm = 61.0
    second = _metrics_row("cranium", {"file_name": "a.ply", "file_path": "/data/a.ply"}, _config(), updated_craniometrics, None, None, None)
    _upsert_cohort_xlsx(cohort_path, second)

    rows = _read_cohort(cohort_path)
    assert len(rows) == 1
    assert rows[0]["depth_mm"] == "61.00"
    # re-exporting the same file reuses its existing cohort_id rather than
    # handing out a new one
    assert rows[0]["cohort_id"] == "C00001"


def test_upsert_cohort_xlsx_falls_back_to_file_name_when_file_path_blank(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    first = _metrics_row("cranium", {"file_name": "a.ply"}, _config(), _craniometrics(), None, None, None)
    _upsert_cohort_xlsx(cohort_path, first)

    updated_craniometrics = _craniometrics()
    updated_craniometrics.depth_mm = 70.0
    second = _metrics_row("cranium", {"file_name": "a.ply"}, _config(), updated_craniometrics, None, None, None)
    _upsert_cohort_xlsx(cohort_path, second)

    rows = _read_cohort(cohort_path)
    assert len(rows) == 1
    assert rows[0]["depth_mm"] == "70.00"


def test_upsert_cohort_xlsx_unions_columns_from_an_older_narrower_schema(tmp_path):
    cohort_path = tmp_path / "cohort.xlsx"
    # simulate an older cohort file with a column today's schema no longer
    # writes (e.g. a since-removed metric) plus a normal row
    wb = Workbook()
    ws = wb.active
    ws.append(["file_path", "file_name", "an_old_removed_column"])
    ws.append(["/data/old.ply", "old.ply", "legacy-value"])
    wb.save(cohort_path)

    new_row = _metrics_row("cranium", {"file_name": "b.ply", "file_path": "/data/b.ply"}, _config(), _craniometrics(), None, None, None)
    _upsert_cohort_xlsx(cohort_path, new_row)

    wb = load_workbook(cohort_path)
    ws = wb.active
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert "an_old_removed_column" in header
    assert "depth_mm" in header

    rows = _read_cohort(cohort_path)
    old_row = next(r for r in rows if r["file_path"] == "/data/old.ply")
    assert old_row["an_old_removed_column"] == "legacy-value"
    assert old_row["depth_mm"] == ""  # new column, blank on the untouched old row

    new_row_out = next(r for r in rows if r["file_path"] == "/data/b.ply")
    assert new_row_out["an_old_removed_column"] == ""  # old column, blank on the new row
    assert new_row_out["depth_mm"] == "59.12"
    assert new_row_out["cohort_id"] == "C00001"
