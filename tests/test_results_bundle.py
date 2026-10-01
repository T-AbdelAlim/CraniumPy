"""tests for results_bundle.py's filename shortening and the two delivery
paths (zip bytes vs writing straight to a folder) sharing the same file set.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.results_bundle import (
    build_analysis_bundle,
    build_meshes_bundle,
    build_results_bundle,
    patient_folder_name,
    results_folder_name,
    shorten_stem,
    stem_from_filename,
    write_analysis_to_folder,
    write_meshes_to_folder,
    write_results_to_folder,
    zip_download_name,
)
from craniumpy_core.craniometrics import extract_measurements
from craniumpy_core.io import load_mesh

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "src" / "craniumpy_core" / "templates" / "template_xy_com.ply"


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("1016510_20210730.000112_edited", "1016510_20210730_edited"),
        ("plain_filename", "plain_filename"),
        ("no_underscores.at.all", "no_underscores"),
        ("trailing.dot_ok", "trailing_ok"),
    ],
)
def test_shorten_stem_collapses_dotted_segments(stem, expected):
    assert shorten_stem(stem) == expected


def test_stem_from_filename_strips_extension_then_shortens():
    assert stem_from_filename("1016510_20210730.000112_edited.ply") == "1016510_20210730_edited"


def test_stem_from_filename_no_extension():
    assert stem_from_filename("no_extension_here") == "no_extension_here"


@pytest.fixture(scope="module")
def sample_result():
    mesh = load_mesh(TEMPLATE_PATH)
    landmarks = np.array([[0.0, 0.0, 60.0], [60.0, 0.0, -20.0], [-60.0, 0.0, -20.0]])
    craniometrics = extract_measurements(mesh)
    return mesh, landmarks, craniometrics


def test_write_results_to_folder_uses_shortened_stem(tmp_path, sample_result):
    mesh, landmarks, craniometrics = sample_result
    results_dir = write_results_to_folder(
        dest_dir=tmp_path,
        original_filename="1016510_20210730.000112_edited.ply",
        registered_mesh=mesh,
        final_mesh=mesh,
        landmarks=landmarks,
        target="cranium",
        craniometrics=craniometrics,
        asymmetry=None,
        config={},
    )
    assert results_dir == tmp_path / "CP_1016510_20210730_edited" / "cranium"
    assert (results_dir / "1016510_20210730_edited_rg.ply").exists()
    assert (results_dir / "1016510_20210730_edited_rg_C.ply").exists()
    assert (results_dir / "1016510_20210730_edited_report_cranial.json").exists()
    assert (results_dir / "1016510_20210730_edited_measurements.png").exists()
    assert (results_dir / "1016510_20210730_edited_summary_cranial.xlsx").exists()
    assert (results_dir / "1016510_20210730_edited_report_cranial.pdf").exists()


def test_build_results_bundle_uses_shortened_stem_too(sample_result):
    mesh, landmarks, craniometrics = sample_result
    zip_bytes = build_results_bundle(
        original_filename="1016510_20210730.000112_edited.ply",
        registered_mesh=mesh,
        final_mesh=mesh,
        landmarks=landmarks,
        target="cranium",
        craniometrics=craniometrics,
        asymmetry=None,
        config={},
    )
    import zipfile
    from io import BytesIO

    names = zipfile.ZipFile(BytesIO(zip_bytes)).namelist()
    assert all(n.startswith("CP_1016510_20210730_edited/cranium/1016510_20210730_edited_") for n in names)


def test_write_meshes_to_folder_writes_only_mesh_files(tmp_path, sample_result):
    mesh, _landmarks, _craniometrics = sample_result
    results_dir = write_meshes_to_folder(
        dest_dir=tmp_path, original_filename="scan.ply", registered_mesh=mesh, final_mesh=mesh, target="cranium", config={}
    )
    # the registration sits at the top, the clipped result under its region
    assert results_dir == tmp_path / "CP_scan"
    assert sorted(p.name for p in results_dir.iterdir()) == ["cranium", "scan_rg.ply"]
    assert sorted(p.name for p in (results_dir / "cranium" / "meshes").iterdir()) == ["scan_rg_C.ply"]


def test_write_meshes_to_folder_records_the_landmarks_next_to_the_rg_mesh(tmp_path, sample_result):
    # an _rg mesh saved straight after align has to carry its own
    # provenance: what was picked, and where those picks landed once
    # registered. batch preprocessing reads this instead of re-picking.
    mesh, _landmarks, _craniometrics = sample_result
    picked = np.array([[1.0, 2.0, 3.0], [-60.0, -10.0, 0.0], [60.0, -10.0, 0.0]])
    registered = np.array([[0.0, 0.0, 70.0], [-65.0, 0.0, 0.0], [65.0, 0.0, 0.0]])

    results_dir = write_meshes_to_folder(
        dest_dir=tmp_path,
        original_filename="scan.ply",
        registered_mesh=mesh,
        final_mesh=None,
        target="cranium",
        config={},
        source_landmarks=picked,
        registered_landmarks=registered,
        com_translation=False,
    )

    assert sorted(p.name for p in results_dir.iterdir()) == ["scan_rg.ply", "scan_rg_landmarks.json"]
    record = json.loads((results_dir / "scan_rg_landmarks.json").read_text())
    assert record["target"] == "cranium"
    assert record["com_translation"] is False
    assert record["picked"]["sellion"] == pytest.approx([1.0, 2.0, 3.0])
    assert record["picked"]["left_tragus"] == pytest.approx([-60.0, -10.0, 0.0])
    assert record["registered"]["right_tragus"] == pytest.approx([65.0, 0.0, 0.0])
    # the secondary frontal landmark is cranial-only and opt-in
    assert record["picked"]["alt_frontal"] is None
    assert record["registered"]["alt_frontal"] is None
    assert record["datetime"]


def test_landmark_record_reports_alt_frontal_instead_of_sellion_when_it_was_used(tmp_path, sample_result):
    # the alt-frontal registration SUBSTITUTES the sellion in the landmark
    # triangle rather than adding a fourth point (registration/rigid.py), so
    # a record claiming both were used would be a lie about the alignment.
    mesh, _landmarks, _craniometrics = sample_result
    picked = np.array([[1.0, 2.0, 3.0], [-60.0, -10.0, 0.0], [60.0, -10.0, 0.0]])
    registered = np.array([[0.0, 30.0, 60.0], [-65.0, 0.0, 0.0], [65.0, 0.0, 0.0]])

    results_dir = write_meshes_to_folder(
        dest_dir=tmp_path,
        original_filename="scan.ply",
        registered_mesh=mesh,
        final_mesh=None,
        target="cranium",
        config={},
        source_landmarks=picked,
        registered_landmarks=registered,
        source_alt_frontal_landmark=np.array([2.0, 40.0, 10.0]),
        used_alt_frontal=True,
    )

    record = json.loads((results_dir / "scan_rg_landmarks.json").read_text())
    assert record["picked"]["alt_frontal"] == pytest.approx([2.0, 40.0, 10.0])
    assert record["picked"]["sellion"] == pytest.approx([1.0, 2.0, 3.0])
    # the registered triangle's first row IS the alt-frontal point here
    assert record["registered"]["alt_frontal"] == pytest.approx([0.0, 30.0, 60.0])
    assert record["registered"]["sellion"] is None


def test_write_analysis_to_folder_creates_mesh_folder_if_missing(tmp_path, sample_result):
    # exporting analysis before ever
    # separately saving meshes should still produce a complete
    # mesh-folder-plus-analysis-subfolder, not just the analysis half.
    mesh, landmarks, craniometrics = sample_result
    assert not (tmp_path / "CP_scan").exists()

    analysis_dir = write_analysis_to_folder(
        dest_dir=tmp_path,
        original_filename="scan.ply",
        registered_mesh=mesh,
        final_mesh=mesh,
        landmarks=landmarks,
        target="cranium",
        craniometrics=craniometrics,
        asymmetry=None,
        config={},
    )

    patient_dir = tmp_path / "CP_scan"
    region_dir = patient_dir / "cranium"
    assert analysis_dir == region_dir / "analysis"
    assert sorted(p.name for p in patient_dir.iterdir()) == ["cranium", "scan_rg.ply"]
    assert sorted(p.name for p in region_dir.iterdir()) == ["analysis", "meshes"]
    assert sorted(p.name for p in (region_dir / "meshes").iterdir()) == ["scan_rg_C.ply"]
    assert sorted(p.name for p in analysis_dir.iterdir()) == [
        "scan_measurements.png",
        "scan_report_cranial.json",
        "scan_report_cranial.pdf",
        "scan_summary_cranial.xlsx",
    ]


def test_write_analysis_to_folder_does_not_rewrite_existing_meshes(tmp_path, sample_result):
    mesh, landmarks, craniometrics = sample_result
    mesh_dir = write_meshes_to_folder(
        dest_dir=tmp_path, original_filename="scan.ply", registered_mesh=mesh, final_mesh=mesh, target="cranium", config={}
    )
    original_mtime = (mesh_dir / "scan_rg.ply").stat().st_mtime_ns

    write_analysis_to_folder(
        dest_dir=tmp_path,
        original_filename="scan.ply",
        registered_mesh=mesh,
        final_mesh=mesh,
        landmarks=landmarks,
        target="cranium",
        craniometrics=craniometrics,
        asymmetry=None,
        config={},
    )

    assert (mesh_dir / "scan_rg.ply").stat().st_mtime_ns == original_mtime


def test_build_meshes_bundle_contains_only_mesh_files(sample_result):
    import zipfile
    from io import BytesIO

    mesh, _landmarks, _craniometrics = sample_result
    zip_bytes = build_meshes_bundle(
        original_filename="scan.ply", registered_mesh=mesh, final_mesh=mesh, target="cranium", config={}
    )
    names = zipfile.ZipFile(BytesIO(zip_bytes)).namelist()
    assert sorted(names) == ["CP_scan/cranium/meshes/scan_rg_C.ply", "CP_scan/scan_rg.ply"]


def test_build_analysis_bundle_nests_analysis_under_mesh_folder(sample_result):
    import zipfile
    from io import BytesIO

    mesh, landmarks, craniometrics = sample_result
    zip_bytes = build_analysis_bundle(
        original_filename="scan.ply",
        registered_mesh=mesh,
        final_mesh=mesh,
        landmarks=landmarks,
        target="cranium",
        craniometrics=craniometrics,
        asymmetry=None,
        config={},
    )
    names = set(zipfile.ZipFile(BytesIO(zip_bytes)).namelist())
    assert names == {
        "CP_scan/scan_rg.ply",
        "CP_scan/cranium/meshes/scan_rg_C.ply",
        "CP_scan/cranium/analysis/scan_report_cranial.json",
        "CP_scan/cranium/analysis/scan_measurements.png",
        "CP_scan/cranium/analysis/scan_summary_cranial.xlsx",
        "CP_scan/cranium/analysis/scan_report_cranial.pdf",
    }


@pytest.mark.parametrize(
    "config, expected_folder",
    [
        ({}, "CP_scan"),
        ({"com_translation": True}, "CP_scan_CoM"),
        ({"com_translation": False}, "CP_scan"),
        ({"alt_frontal_landmark": {"x": 0.0, "y": -37.0, "z": 73.0}}, "CP_scan_4"),
        ({"alt_frontal_landmark": {"x": 0.0, "y": -37.0, "z": 73.0}, "com_translation": True}, "CP_scan_4_CoM"),
        ({"alt_frontal_landmark": None, "com_translation": True}, "CP_scan_CoM"),
    ],
)
def test_patient_folder_name_reflects_landmark_count_and_com(config, expected_folder):
    # the patient folder says what the REGISTRATION was, and nothing about
    # which region was analysed - that's the subfolder's job, so both
    # regions of one scan share one folder instead of sitting side by side.
    assert patient_folder_name("scan.ply", config) == expected_folder
    assert results_folder_name("scan.ply", "cranium", config) == f"{expected_folder}/cranium"


def test_both_regions_of_one_scan_share_a_patient_folder():
    cranial = results_folder_name("scan.ply", "cranium", {})
    facial = results_folder_name("scan.ply", "face", {})

    assert cranial == "CP_scan/cranium"
    assert facial == "CP_scan/face_and_forehead"
    assert cranial.split("/")[0] == facial.split("/")[0]


def test_zip_download_name_has_no_path_separator():
    # it ends up in a Content-Disposition filename, where a slash would be
    assert zip_download_name("scan.ply", "face", {}) == "CP_scan_face_and_forehead"
