"""regression test - the ported craniometrics has to give the same numbers as
the old algorithm on the same mesh.

baseline came from running the unmodified old CranioMetrics math against
tests/fixtures/test_mesh.ply, see
tests/fixtures/test_mesh_craniometrics_baseline.json for the details.

tolerances aren't zero because trimesh's Trimesh.section and pyvista/VTK's
slicer are different implementations of the same operation - close, but not
bit for bit identical.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from craniumpy_core.craniometrics import SliceProfile, _select_slice_index, extract_measurements, frontal_bossing
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


def test_select_slice_index_min_y_noop_when_nothing_eligible():
    # if every slice is below the floor (a degenerate/tiny mesh), fall back
    # to the plain deepest-slice pick rather than raising or picking nothing
    profiles = [
        SliceProfile(y=0, depth=100.0, breadth=90.0, x_min=-45, x_max=45, z_min=-50, z_max=50),
        SliceProfile(y=5, depth=120.0, breadth=95.0, x_min=-47, x_max=48, z_min=-60, z_max=60),
    ]
    assert _select_slice_index(profiles, min_y=1000) == 1


# --- frontal_bossing --------------------------------------------------


def _sagittal_grid_mesh(y: np.ndarray, z: np.ndarray, xs: np.ndarray | None = None) -> trimesh.Trimesh:
    """a sheet extruded along x, with the same (y, z) sagittal profile at
    every x column - gives mesh.section(plane_normal=[1,0,0], ...) real
    interior triangle geometry to intersect, instead of the degenerate
    single-column-wide case (confirmed via manual testing to produce
    nonsensical intersection points when the slicing plane is exactly
    coincident with a 2-column-wide strip's own centerline)."""
    if xs is None:
        xs = np.linspace(-20.0, 20.0, 9)
    ny = len(y)
    verts = np.empty((len(xs) * ny, 3))
    for i, xv in enumerate(xs):
        verts[i * ny : (i + 1) * ny, 0] = xv
        verts[i * ny : (i + 1) * ny, 1] = y
        verts[i * ny : (i + 1) * ny, 2] = z
    faces = []
    for i in range(len(xs) - 1):
        for j in range(ny - 1):
            a, b = i * ny + j, i * ny + j + 1
            c, d = (i + 1) * ny + j, (i + 1) * ny + j + 1
            faces.append([a, b, c])
            faces.append([b, d, c])
    return trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)


def test_frontal_bossing_bulging_forehead():
    # a downward parabola above sellion (y=0), peaking at y=40, z=20 - the
    # unique most-anterior point over the sampled range. sellion is given
    # sitting right on the surface at y=0 - frontal_bossing snaps whatever
    # it's given onto the mesh (see its docstring), so a sellion that isn't
    # actually near the surface would have the snap itself move it and
    # throw off the expected angle below.
    y = np.linspace(0.0, 100.0, 300)
    z = -0.005 * (y - 40.0) ** 2 + 20.0
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, z[0]])

    result = frontal_bossing(mesh, sellion)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(40.0, abs=1.0)
    assert result.frontal_point[2] == pytest.approx(20.0, abs=0.5)
    expected_angle = np.degrees(np.arctan2(40.0, 20.0 - z[0]))
    assert result.angle_deg == pytest.approx(expected_angle, abs=2.0)


def test_frontal_bossing_receding_forehead_reads_a_larger_angle_than_bulging():
    # near-vertical rise, barely any forward bulge - most-anterior point is
    # just the top of the range, giving a near-90deg (flatter/receding) angle
    y = np.linspace(0.0, 100.0, 300)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(100.0, abs=1.0)
    expected_angle = np.degrees(np.arctan2(100.0, 2.0))
    assert result.angle_deg == pytest.approx(expected_angle, abs=1.0)
    assert result.angle_deg > 80.0


def test_frontal_bossing_excludes_points_below_sellion():
    # a much-more-anterior "nose" sits below sellion (y<0, z=50) - the
    # forehead's own bulge above sellion (max z=20, at y=40) is far less
    # anterior, but must still win since the nose isn't part of the forehead
    y = np.linspace(-40.0, 100.0, 400)
    z = np.where(y < 0.0, 50.0, -0.005 * (y - 40.0) ** 2 + 20.0)
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion)

    assert result is not None
    assert result.frontal_point[1] > 0.0
    assert result.frontal_point[2] == pytest.approx(20.0, abs=0.5)


def test_frontal_bossing_none_when_plane_misses_mesh():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([500.0, 0.0, 0.0])  # far outside the mesh's x range

    assert frontal_bossing(mesh, sellion) is None


def test_frontal_bossing_none_when_nothing_above_sellion():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 1000.0, 0.0])  # above every point on the mesh

    assert frontal_bossing(mesh, sellion) is None


def test_frontal_bossing_profile_is_non_empty():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion)

    assert result is not None
    assert len(result.profile) > 0
