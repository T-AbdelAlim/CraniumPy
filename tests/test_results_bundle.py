"""tests for results_bundle.py's filename shortening and the two delivery
paths (zip bytes vs writing straight to a folder) sharing the same file set.
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.results_bundle import (
    build_results_bundle,
    results_folder_name,
    shorten_stem,
    stem_from_filename,
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
