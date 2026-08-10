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

from craniumpy_core.craniometrics import SliceProfile, _select_slice_index, extract_measurements
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


def test_select_slice_index_min_y_floor_excludes_ear_level_slice():
    # a small/pediatric-scale profile stack where the deepest slice sits at
    # ear level (y=5) with breadth narrow enough (150mm) to slip past the
    # 180mm ear heuristic entirely - a real case found on a small head where
    # breadth alone wasn't enough to rule out the ears (see
    # extract_measurements's landmarks param, which is what supplies min_y).
    profiles = [
        SliceProfile(y=0, depth=150.0, breadth=140.0, x_min=-70, x_max=70, z_min=-70, z_max=80),
        SliceProfile(y=5, depth=200.0, breadth=150.0, x_min=-75, x_max=75, z_min=-100, z_max=100),
        SliceProfile(y=10, depth=160.0, breadth=145.0, x_min=-72, x_max=73, z_min=-80, z_max=80),
        SliceProfile(y=20, depth=155.0, breadth=140.0, x_min=-70, x_max=70, z_min=-75, z_max=80),
    ]
    # without a floor, the naive deepest-slice pick lands right at the
    # ear-level slice - breadth (150mm) never trips the 180mm heuristic
    assert _select_slice_index(profiles) == 1
    # a floor just above the ear landmarks rules that slice out
    assert _select_slice_index(profiles, min_y=10) == 2


def test_select_slice_index_clears_ear_plateau_not_just_landmark_floor():
    # shaped after a real breadth-vs-height profile that still measured
    # through the ears with only a fixed margin above the tragus landmarks:
    # breadth stays on a wide plateau (~150mm) all the way through the
    # pinna, then drops sharply (~150 -> 135mm) once the slice actually
    # clears the top of the ear, and stays down from there. a bare min_y
    # floor a few mm above the tragus lands well inside that plateau -
    # ear_clear_fraction is what actually rules the whole ear zone out.
    profiles = [
        SliceProfile(y=0, depth=190.0, breadth=155.0, x_min=-77, x_max=78, z_min=-95, z_max=95),
        SliceProfile(y=5, depth=192.0, breadth=152.0, x_min=-76, x_max=76, z_min=-96, z_max=96),
        SliceProfile(y=10, depth=196.0, breadth=154.0, x_min=-77, x_max=77, z_min=-98, z_max=98),
        SliceProfile(y=15, depth=198.0, breadth=155.0, x_min=-78, x_max=77, z_min=-99, z_max=99),
        SliceProfile(y=20, depth=196.0, breadth=150.0, x_min=-75, x_max=75, z_min=-98, z_max=98),
        SliceProfile(y=25, depth=195.0, breadth=143.0, x_min=-71, x_max=72, z_min=-97, z_max=98),
        SliceProfile(y=28, depth=194.0, breadth=135.0, x_min=-68, x_max=68, z_min=-97, z_max=97),
        SliceProfile(y=35, depth=193.0, breadth=137.0, x_min=-69, x_max=68, z_min=-96, z_max=97),
    ]
    # a small floor (min_y=5, well above y=0) still lands inside the ear
    # plateau and picks the deepest slice there (y=15, depth 198 - the
    # plateau's own peak) if ear-clearing isn't applied
    assert _select_slice_index(profiles, min_y=5, ear_clear_fraction=1.0) == 3  # y=15
    # with ear-clearing on, the same floor rules out the whole plateau and
    # lands past the drop, at y=28 (breadth 135 <= 90% of the 155mm peak)
    assert _select_slice_index(profiles, min_y=5, ear_clear_fraction=0.9) == 6  # y=28


def test_select_slice_index_min_y_noop_when_nothing_eligible():
    # if every slice is below the floor (a degenerate/tiny mesh), fall back
    # to the plain deepest-slice pick rather than raising or picking nothing
    profiles = [
        SliceProfile(y=0, depth=100.0, breadth=90.0, x_min=-45, x_max=45, z_min=-50, z_max=50),
        SliceProfile(y=5, depth=120.0, breadth=95.0, x_min=-47, x_max=48, z_min=-60, z_max=60),
    ]
    assert _select_slice_index(profiles, min_y=1000) == 1
