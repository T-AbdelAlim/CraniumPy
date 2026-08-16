"""tests for results_bundle.py's filename shortening and the two delivery
paths (zip bytes vs writing straight to a folder) sharing the same file set.
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.results_bundle import (
    build_analysis_bundle,
    build_meshes_bundle,
    build_results_bundle,
    results_folder_name,
    shorten_stem,
    stem_from_filename,
    write_analysis_to_folder,
    write_meshes_to_folder,
    write_results_to_folder,
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
    assert results_dir == tmp_path / "CP_1016510_20210730_edited_C_3"
    assert (results_dir / "1016510_20210730_edited_rg.ply").exists()
    assert (results_dir / "1016510_20210730_edited_rg_C.ply").exists()
    assert (results_dir / "1016510_20210730_edited_report.json").exists()
    assert (results_dir / "1016510_20210730_edited_measurements.png").exists()
    assert (results_dir / "1016510_20210730_edited_summary.xlsx").exists()
    assert (results_dir / "1016510_20210730_edited_report.pdf").exists()


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
    assert all(n.startswith("CP_1016510_20210730_edited_C_3/1016510_20210730_edited_") for n in names)


def test_write_meshes_to_folder_writes_only_mesh_files(tmp_path, sample_result):
    mesh, _landmarks, _craniometrics = sample_result
    results_dir = write_meshes_to_folder(
        dest_dir=tmp_path, original_filename="scan.ply", registered_mesh=mesh, final_mesh=mesh, target="cranium", config={}
    )
    assert results_dir == tmp_path / "CP_scan_C_3"
    assert sorted(p.name for p in results_dir.iterdir()) == ["scan_rg.ply", "scan_rg_C.ply"]


def test_write_analysis_to_folder_creates_mesh_folder_if_missing(tmp_path, sample_result):
    # the user's explicit requirement: exporting analysis before ever
    # separately saving meshes should still produce a complete
    # mesh-folder-plus-analysis-subfolder, not just the analysis half.
    mesh, landmarks, craniometrics = sample_result
    assert not (tmp_path / "CP_scan_C_3").exists()

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

    mesh_dir = tmp_path / "CP_scan_C_3"
    assert analysis_dir == mesh_dir / "analysis"
    assert sorted(p.name for p in mesh_dir.iterdir()) == ["analysis", "scan_rg.ply", "scan_rg_C.ply"]
    assert sorted(p.name for p in analysis_dir.iterdir()) == [
        "scan_measurements.png",
        "scan_report.json",
        "scan_report.pdf",
        "scan_summary.xlsx",
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
    assert sorted(names) == ["CP_scan_C_3/scan_rg.ply", "CP_scan_C_3/scan_rg_C.ply"]


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
        "CP_scan_C_3/scan_rg.ply",
        "CP_scan_C_3/scan_rg_C.ply",
        "CP_scan_C_3/analysis/scan_report.json",
        "CP_scan_C_3/analysis/scan_measurements.png",
        "CP_scan_C_3/analysis/scan_summary.xlsx",
        "CP_scan_C_3/analysis/scan_report.pdf",
    }


@pytest.mark.parametrize(
    "config, expected_suffix",
    [
        ({}, "C_3"),
        ({"com_translation": True}, "C_3_CoM"),
        ({"com_translation": False}, "C_3"),
        ({"alt_frontal_landmark": {"x": 0.0, "y": -37.0, "z": 73.0}}, "C_4"),
        ({"alt_frontal_landmark": {"x": 0.0, "y": -37.0, "z": 73.0}, "com_translation": True}, "C_4_CoM"),
        ({"alt_frontal_landmark": None, "com_translation": True}, "C_3_CoM"),
    ],
)
def test_results_folder_name_reflects_landmark_count_and_com(config, expected_suffix):
    folder = results_folder_name("scan.ply", "cranium", config)
    assert folder == f"CP_scan_{expected_suffix}"


def test_results_folder_name_facial_target_uses_f_suffix():
    folder = results_folder_name("scan.ply", "face", {})
    assert folder == "CP_scan_F_3"
