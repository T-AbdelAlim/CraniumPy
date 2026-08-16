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

from craniumpy_core.craniometrics import (
    SliceProfile,
    _select_forehead_half,
    _select_slice_index,
    extract_measurements,
    frontal_bossing,
)
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
    # a downward parabola above sellion (y=0), peaking at y=40, z=20.
    # slice_height=40 anchors the forehead point exactly at that peak, so
    # this exercises the same "point of maximum forward bulge" case the
    # old argmax-only version always found, just now reached by explicitly
    # anchoring to a given slice height (see frontal_bossing's docstring)
    # instead of independently searching for it. sellion is given sitting
    # right on the surface at y=0 - frontal_bossing snaps whatever it's
    # given onto the mesh, so a sellion that isn't actually near the
    # surface would have the snap itself move it and throw off the
    # expected angle below.
    y = np.linspace(0.0, 100.0, 300)
    z = -0.005 * (y - 40.0) ** 2 + 20.0
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, z[0]])

    result = frontal_bossing(mesh, sellion, slice_height=40.0)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(40.0, abs=1.0)
    assert result.frontal_point[2] == pytest.approx(20.0, abs=0.5)
    expected_angle = np.degrees(np.arctan2(40.0, 20.0 - z[0]))
    assert result.angle_deg == pytest.approx(expected_angle, abs=2.0)
    assert result.slice_height == pytest.approx(40.0)


def test_frontal_bossing_interpolates_between_profile_points():
    # a straight line, not a value directly sampled by the mesh grid below
    # (y is stepped in exact multiples of 100/299) - forces the crossing
    # to actually land between two profile points rather than exactly on
    # one, exercising the interpolation itself rather than a coincidence.
    y = np.linspace(0.0, 100.0, 300)
    z = -0.005 * (y - 40.0) ** 2 + 20.0
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, z[0]])
    slice_height = 40.333

    result = frontal_bossing(mesh, sellion, slice_height=slice_height)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(slice_height, abs=0.5)
    expected_z = -0.005 * (slice_height - 40.0) ** 2 + 20.0
    assert result.frontal_point[2] == pytest.approx(expected_z, abs=0.5)


def test_frontal_bossing_slice_height_outside_forehead_range_falls_back_to_most_anterior():
    # slice_height (200) sits well above the tallest point on this
    # forehead (y maxes out at 100) - falls back to the most anterior (max
    # z) point above sellion, same as the old unconditional-argmax
    # behavior, rather than extrapolating or failing.
    y = np.linspace(0.0, 100.0, 300)
    z = -0.005 * (y - 40.0) ** 2 + 20.0
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, z[0]])

    result = frontal_bossing(mesh, sellion, slice_height=200.0)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(40.0, abs=1.0)
    assert result.frontal_point[2] == pytest.approx(20.0, abs=0.5)


def test_frontal_bossing_receding_forehead_reads_a_larger_angle_than_bulging():
    # near-vertical rise, barely any forward bulge - a large (flatter/
    # receding) angle at any height comfortably on the forehead.
    y = np.linspace(0.0, 100.0, 300)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion, slice_height=60.0)

    assert result is not None
    assert result.frontal_point[1] == pytest.approx(60.0, abs=1.0)
    assert result.frontal_point[2] == pytest.approx(1.2, abs=0.5)
    expected_angle = np.degrees(np.arctan2(60.0, 1.2))
    assert result.angle_deg == pytest.approx(expected_angle, abs=1.0)
    assert result.angle_deg > 80.0


def test_frontal_bossing_excludes_points_below_sellion():
    # a much-more-anterior "nose" sits below sellion (y<0, z=50) - the
    # forehead's own bulge above sellion (max z=20, at y=40) is far less
    # anterior, but the above-sellion restriction must keep the nose out
    # of the forehead arc entirely regardless of slice_height.
    y = np.linspace(-40.0, 100.0, 400)
    z = np.where(y < 0.0, 50.0, -0.005 * (y - 40.0) ** 2 + 20.0)
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion, slice_height=40.0)

    assert result is not None
    assert result.frontal_point[1] > 0.0
    assert result.frontal_point[2] == pytest.approx(20.0, abs=0.5)


def test_frontal_bossing_none_when_plane_misses_mesh():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([500.0, 0.0, 0.0])  # far outside the mesh's x range

    assert frontal_bossing(mesh, sellion, slice_height=50.0) is None


def test_frontal_bossing_none_when_nothing_above_sellion():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 1000.0, 0.0])  # above every point on the mesh

    assert frontal_bossing(mesh, sellion, slice_height=50.0) is None


def test_frontal_bossing_profile_is_non_empty():
    y = np.linspace(0.0, 100.0, 100)
    z = 0.02 * y
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 0.0])

    result = frontal_bossing(mesh, sellion, slice_height=50.0)

    assert result is not None
    assert len(result.profile) > 0


def test_select_forehead_half_picks_the_side_near_sellion_regardless_of_arc_order():
    # the shape frontal_bossing's own above-sellion arc takes on a real
    # closed-cap mesh: one unbroken run from the forehead, over the vertex
    # (the y maximum), down to the occiput - both ends sit near sellion's
    # own HEIGHT (y), but nowhere near each other in DEPTH (z). sellion
    # sits right next to the forehead end (z=70.9), clear across the head
    # from the occipital end (z=-82).
    sellion = np.array([0.0, 0.0, 70.5])
    front_to_back = np.array(
        [
            [0.0, 2.4, 70.9],
            [0.0, 80.0, 90.0],
            [0.0, 150.0, 40.0],  # crown/vertex - the y maximum
            [0.0, 90.0, -30.0],
            [0.0, 4.6, -82.0],
        ]
    )

    forward = _select_forehead_half(front_to_back, sellion)
    assert forward[-1, 1] == pytest.approx(150.0)  # ends at the crown
    assert forward[0, 2] == pytest.approx(70.9)  # starts on the forehead side

    # the exact same physical arc, walked from the other end first - this
    # is the case that used to silently pick the occipital point instead
    # (see frontal_bossing's docstring for why mesh.section()'s own
    # traversal direction can't be trusted to always start at the front).
    backward = _select_forehead_half(front_to_back[::-1], sellion)
    assert backward[-1, 1] == pytest.approx(150.0)
    assert backward[0, 2] == pytest.approx(70.9)


def test_frontal_bossing_full_head_profile_finds_frontal_point_not_occipital():
    # a full front-to-back sagittal sweep (a semicircle in the y-z plane) -
    # the shape a real closed-cap cranial/facial mesh's section actually
    # produces, unlike every other test above, which only ever hands
    # frontal_bossing an isolated forehead arc with no occiput on it at all
    # to possibly confuse it with.
    theta = np.linspace(0.0, np.pi, 300)
    y = 100.0 * np.sin(theta)
    z = -100.0 * np.cos(theta)  # theta=0: occiput (y=0, z=-100); theta=pi: forehead base (y=0, z=100)
    mesh = _sagittal_grid_mesh(y, z)
    sellion = np.array([0.0, 0.0, 95.0])

    result = frontal_bossing(mesh, sellion, slice_height=50.0)

    assert result is not None
    # the crown sits at z=0 (theta=pi/2) - a point correctly picked from
    # the frontal half has z somewhere between sellion (95) and the crown
    # (0), nowhere near the occiput's z=-100.
    assert result.frontal_point[2] > 0.0
