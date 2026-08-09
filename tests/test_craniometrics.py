"""regression test - the ported craniometrics has to give the same numbers as
the old algorithm on the same mesh.

baseline came from running the unmodified old CranioMetrics math against
resources/test_mesh/test_mesh.ply, see
tests/fixtures/test_mesh_craniometrics_baseline.json for the details.

tolerances aren't zero because trimesh's Trimesh.section and pyvista/VTK's
slicer are different implementations of the same operation - close, but not
bit for bit identical.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from craniumpy_core.craniometrics import extract_measurements
from craniumpy_core.io import load_mesh

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "test_mesh_craniometrics_baseline.json"


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


@pytest.fixture(scope="module")
def measurements(baseline):
    mesh_path = REPO_ROOT / baseline["source_mesh"]
    mesh = load_mesh(mesh_path)
    return extract_measurements(mesh)


def test_slice_height_matches(measurements, baseline):
    assert measurements.slice_height == pytest.approx(baseline["slice_height"], abs=1.0)


def test_depth_matches(measurements, baseline):
    assert measurements.depth_mm == pytest.approx(baseline["depth_mm"], rel=0.02)


def test_breadth_matches(measurements, baseline):
    assert measurements.breadth_mm == pytest.approx(baseline["breadth_mm"], rel=0.02)


def test_cephalic_index_matches(measurements, baseline):
    assert measurements.cephalic_index == pytest.approx(baseline["cephalic_index"], rel=0.02)


def test_circumference_matches(measurements, baseline):
    assert measurements.circumference_cm == pytest.approx(baseline["circumference_cm"], rel=0.02)


def test_volume_matches(measurements):
    # not actually comparing against the legacy baseline number here anymore.
    # test_mesh.ply is the raw, unrepaired scan - not watertight - and the old
    # baseline just called mesh.volume on it directly, which is a divergence-
    # theorem computation that doesn't mean much on an open mesh anyway.
    # extract_measurements now caps a throwaway copy with pymeshfix first
    # (see _watertight_volume_cc) so this number is real, at the cost of no
    # longer matching whatever the old open-mesh computation happened to spit
    # out - checked by hand that it's in the right ballpark for a kid's head
    # (2400-2700 cc is normal), not pinned tighter than that since there's no
    # ground truth for what a repaired version of this exact scan "should"
    # measure.
    assert 1500 < measurements.mesh_volume_cc < 3500


@pytest.mark.parametrize("field", ["front_opt", "occ_opt", "lh_opt", "rh_opt"])
def test_optima_points_match(measurements, baseline, field):
    got = np.asarray(getattr(measurements, field))
    expected = np.asarray(baseline[field])
    np.testing.assert_allclose(got, expected, atol=2.0)
