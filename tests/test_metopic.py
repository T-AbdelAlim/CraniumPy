"""tests for metopic.py.

there's no clinical baseline for any of this (see metopic.py's module
docstring) - these check the math against synthetic contours with known
shapes instead: a plain fitted parabola (should recover its own
coefficients and read ~zero deviation everywhere), a bump added at a known
position (should raise frontal-angle-related and ridge metrics, not
temporal ones), and a dip added at a known position (the reverse). the
"known position" part matters - arc length isn't linear in x for a curved
contour, so tests that need a perturbation to land inside a specific
region window find that window's actual x-range by inverting the
contour's own u(x) mapping, rather than guessing.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from craniumpy_core.craniometrics import find_hc_slice_height
from craniumpy_core.metopic import (
    RIDGE_APEX_X_WINDOW_MM,
    SHOULDER_INNER_U,
    TEMPORAL_INNER_U,
    TEMPORAL_OUTER_U,
    _arc_length,
    _deviation_profile,
    _fit_parabola,
    _find_midline_u,
    _gradient_and_curvature,
    _smooth,
    analyze_forehead,
    forehead_contour,
)
from craniumpy_core.pipeline import hc_slice_height_facial_frame, register
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE


def _ellipsoid_with_landmarks() -> tuple[trimesh.Trimesh, np.ndarray]:
    """head-scale ellipsoid with landmarks in roughly REFERENCE_TRIANGLE's
    layout - same construction tests/test_pipeline.py uses, kept local here
    since test_nicp.py's own synthetic-geometry helper is local too."""
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    v = np.asarray(mesh.vertices).copy()
    mesh.vertices = v * np.array([70.0, 90.0, 60.0]) + np.array([5.0, -20.0, 8.0])
    landmarks = REFERENCE_TRIANGLE * np.array([0.9, 1.1, 0.95]) + np.array([5.0, -20.0, 8.0])
    return mesh, landmarks


def _strip_mesh(x: np.ndarray, z: np.ndarray, y0: float = 100.0) -> trimesh.Trimesh:
    """a thin triangulated strip whose cross-section at y=y0 is exactly the
    given (x, z) curve - just enough geometry for mesh.section() to have
    something real to slice, without needing a full head-shaped mesh for
    tests that only care about the 2D contour math."""
    verts = np.empty((2 * len(x), 3))
    verts[0::2] = np.column_stack([x, np.full_like(x, y0 - 1), z])
    verts[1::2] = np.column_stack([x, np.full_like(x, y0 + 1), z])
    faces = []
    for i in range(len(x) - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * (i + 1), 2 * (i + 1) + 1
        faces.append([a, b, c])
        faces.append([b, d, c])
    return trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)


def _rounded_forehead(x: np.ndarray, a: float = -0.006, c: float = 40.0) -> np.ndarray:
    return a * x**2 + c


def _find_x_for_u(mesh: trimesh.Trimesh, y0: float, target_u: float) -> float:
    """inverts a contour's own arc-length parameterization to find the x
    where normalized arc length u actually lands at target_u - needed
    because u isn't linear in x for a curved contour, so a test that wants
    a perturbation inside (or outside) a specific region window can't just
    guess an x offset."""
    raw = forehead_contour(mesh, y0)
    x, z = _smooth(raw[:, 0]), _smooth(raw[:, 1])
    s = _arc_length(np.column_stack([x, z]))
    u = s / s[-1]
    u0 = _find_midline_u(x, u)
    idx = int(np.argmin(np.abs(u - (u0 + target_u))))
    return float(x[idx])


# --- pure math, no mesh involved ---------------------------------------


def test_fit_parabola_recovers_known_coefficients():
    x = np.linspace(-60, 60, 200)
    z = -0.01 * x**2 + 35.0
    a, c = _fit_parabola(x, z)
    assert a == pytest.approx(-0.01, abs=1e-4)
    assert c == pytest.approx(35.0, abs=0.1)


def test_fit_parabola_is_robust_to_a_local_outlier_region():
    # a small cluster of points well off the parabola (simulating a
    # ridge/hollow bleeding into the fit window) shouldn't drag the fit
    # nearly as far as a plain least-squares fit would.
    x = np.linspace(-60, 60, 200)
    z = -0.01 * x**2 + 35.0
    outliers = np.abs(x) < 5
    z_contaminated = z.copy()
    z_contaminated[outliers] += 15.0

    a_robust, c_robust = _fit_parabola(x, z_contaminated)
    A = np.column_stack([x**2, np.ones_like(x)])
    a_plain, c_plain = np.linalg.lstsq(A, z_contaminated, rcond=None)[0]

    assert abs(c_robust - 35.0) < abs(c_plain - 35.0)


def test_deviation_profile_sign_convention():
    # positive = more anterior (larger z) than the parabola predicts
    x = np.array([-10.0, 0.0, 10.0])
    a, c = -0.01, 30.0
    z_above = (a * x**2 + c) + 5.0
    z_below = (a * x**2 + c) - 5.0
    assert (_deviation_profile(x, z_above, a, c) > 0).all()
    assert (_deviation_profile(x, z_below, a, c) < 0).all()


def test_curvature_positive_for_outward_convex_bulge():
    x = np.linspace(-60, 60, 300)
    z = -0.01 * x**2 + 40.0  # a>0 in magnitude, peak (most anterior) at center
    s = _arc_length(np.column_stack([x, z]))
    _, kappa = _gradient_and_curvature(x, z, s)
    center = np.argmin(np.abs(x))
    assert kappa[center] > 0


def test_curvature_zero_for_a_straight_line():
    x = np.linspace(-60, 60, 200)
    z = np.full_like(x, 10.0)
    s = _arc_length(np.column_stack([x, z]))
    _, kappa = _gradient_and_curvature(x, z, s)
    np.testing.assert_allclose(kappa, 0.0, atol=1e-9)


def test_midline_u_interpolates_between_bracketing_points():
    x = np.array([-2.0, -1.0, 1.0, 2.0])
    u = np.array([0.0, 0.25, 0.75, 1.0])
    # crosses zero exactly halfway between index 1 (-1.0) and 2 (1.0)
    assert _find_midline_u(x, u) == pytest.approx(0.5, abs=1e-9)


# --- forehead_contour -----------------------------------------------------


def test_forehead_contour_none_when_plane_misses_mesh():
    x = np.linspace(-60, 60, 100)
    mesh = _strip_mesh(x, _rounded_forehead(x))
    assert forehead_contour(mesh, 500.0) is None


def test_forehead_contour_none_when_it_doesnt_cross_the_midline():
    # entirely on one side of x=0 - not a genuine forehead-spanning arc
    x = np.linspace(10.0, 60.0, 100)
    mesh = _strip_mesh(x, _rounded_forehead(x))
    assert forehead_contour(mesh, 100.0) is None


def test_forehead_contour_ordered_left_to_right():
    x = np.linspace(-60, 60, 100)
    mesh = _strip_mesh(x, _rounded_forehead(x))
    contour = forehead_contour(mesh, 100.0)
    assert contour is not None
    assert (np.diff(contour[:, 0]) > 0).all()


# --- analyze_forehead end-to-end, on a synthetic strip mesh ---------------


def test_analyze_forehead_baseline_reads_near_zero_deviation_metrics():
    # a contour that's an exact parabola everywhere has nothing for the
    # fit to disagree with - every deviation-derived metric should read
    # essentially zero, and the frontal angle should be a single stable
    # number determined purely by the base curvature.
    x = np.linspace(-70, 70, 300)
    mesh = _strip_mesh(x, _rounded_forehead(x))
    result = analyze_forehead(mesh, 100.0)

    assert result is not None
    assert result.ridge_protrusion_mm == pytest.approx(0.0, abs=1e-3)
    assert result.ridge_area_mm2 == pytest.approx(0.0, abs=1e-2)
    assert result.left_temporal_hollowing == pytest.approx(0.0, abs=1e-3)
    assert result.right_temporal_hollowing == pytest.approx(0.0, abs=1e-3)
    assert result.parabolic_deviation_index == pytest.approx(0.0, abs=1e-2)
    assert 90.0 < result.frontal_angle_deg < 180.0


def test_analyze_forehead_central_bump_sharpens_frontal_angle_and_raises_ridge_metrics():
    x = np.linspace(-70, 70, 300)
    baseline = analyze_forehead(_strip_mesh(x, _rounded_forehead(x)), 100.0)

    bump = _rounded_forehead(x) + 6.0 * np.exp(-(x**2) / (2 * 6.0**2))
    bumped = analyze_forehead(_strip_mesh(x, bump), 100.0)

    assert bumped is not None and baseline is not None
    # sharper central protrusion -> more pointed -> smaller angle
    assert bumped.frontal_angle_deg < baseline.frontal_angle_deg
    assert bumped.ridge_protrusion_mm > baseline.ridge_protrusion_mm + 1.0
    assert bumped.ridge_area_mm2 > baseline.ridge_area_mm2
    assert bumped.midline_curvature_concentration > baseline.midline_curvature_concentration
    # a purely central perturbation shouldn't manufacture temporal signal
    assert bumped.left_temporal_hollowing == pytest.approx(0.0, abs=0.05)
    assert bumped.right_temporal_hollowing == pytest.approx(0.0, abs=0.05)


def test_ridge_apex_is_the_most_anterior_point_within_the_x_window_not_the_max_deviation_point():
    # M has to be "the most forward point near the midline", a physical
    # location - not whichever point happens to deviate most from the
    # fitted parabola. built so the two definitions disagree: a taller peak
    # sits off-center (but still inside +/-RIDGE_APEX_X_WINDOW_MM) at
    # x=8, and a shorter bump sits exactly at x=0 - the old
    # max-deviation-in-a-u-window logic could easily have picked the x=0
    # bump instead (it's dead center), but the actual most-anterior point
    # is unambiguously the x=8 one.
    assert 8.0 < RIDGE_APEX_X_WINDOW_MM  # otherwise this test isn't exercising the window at all
    x = np.linspace(-70, 70, 400)
    base = _rounded_forehead(x)
    off_center_taller = 10.0 * np.exp(-((x - 8.0) ** 2) / (2 * 3.0**2))
    on_center_shorter = 4.0 * np.exp(-(x**2) / (2 * 3.0**2))
    z = base + off_center_taller + on_center_shorter

    result = analyze_forehead(_strip_mesh(x, z), 100.0)
    assert result is not None
    M, _, _ = result.frontal_angle_points
    assert M[0] == pytest.approx(8.0, abs=1.0)


def test_ridge_apex_ignores_a_taller_point_outside_the_x_window():
    # a peak well outside +/-RIDGE_APEX_X_WINDOW_MM, even a much taller one,
    # must not become M - confirms the window is actually enforced, not
    # just "whichever peak is tallest anywhere."
    x = np.linspace(-70, 70, 400)
    base = _rounded_forehead(x)
    far_taller_peak = 15.0 * np.exp(-((x - 40.0) ** 2) / (2 * 3.0**2))
    z = base + far_taller_peak

    result = analyze_forehead(_strip_mesh(x, z), 100.0)
    assert result is not None
    M, _, _ = result.frontal_angle_points
    assert abs(M[0]) <= RIDGE_APEX_X_WINDOW_MM


def test_mcc_is_higher_for_a_narrower_central_ridge_than_a_broad_one():
    # same peak height, different width - a sharper/narrower ridge should
    # concentrate its curvature more tightly around the midline than a
    # broad, gentle one does, even though both raise ridge_protrusion by
    # about the same amount.
    x = np.linspace(-70, 70, 300)
    base = _rounded_forehead(x)
    narrow = analyze_forehead(_strip_mesh(x, base + 6.0 * np.exp(-(x**2) / (2 * 4.0**2))), 100.0)
    broad = analyze_forehead(_strip_mesh(x, base + 6.0 * np.exp(-(x**2) / (2 * 20.0**2))), 100.0)

    assert narrow is not None and broad is not None
    assert narrow.midline_curvature_concentration > broad.midline_curvature_concentration


def test_analyze_forehead_lateral_dip_raises_only_the_matching_side():
    x = np.linspace(-70, 70, 300)
    base = _rounded_forehead(x)
    baseline_mesh = _strip_mesh(x, base)
    baseline = analyze_forehead(baseline_mesh, 100.0)
    assert baseline is not None

    # place the dip at an x that actually lands inside the LEFT temporal
    # window, found via this exact contour's own u(x) mapping rather than
    # assumed - the temporal windows are u0 +/- [INNER, OUTER] on each side.
    target_u = -(TEMPORAL_INNER_U + TEMPORAL_OUTER_U) / 2.0
    x_dip = _find_x_for_u(baseline_mesh, 100.0, target_u)

    dipped = base - 5.0 * np.exp(-((x - x_dip) ** 2) / (2 * 6.0**2))
    result = analyze_forehead(_strip_mesh(x, dipped), 100.0)

    assert result is not None
    assert result.left_temporal_hollowing > baseline.left_temporal_hollowing + 1e-4
    assert result.right_temporal_hollowing == pytest.approx(0.0, abs=1e-3)
    assert result.left_max_temporal_depth_mm > 1.0
    # a purely lateral, outside-the-frontal-angle-window perturbation
    # shouldn't move the frontal angle much
    assert result.frontal_angle_deg == pytest.approx(baseline.frontal_angle_deg, abs=5.0)


def test_analyze_forehead_shoulder_fit_windows_land_where_documented():
    # sanity check on the module's own constants, not a numeric baseline -
    # the shoulder windows used for the parabola fit have to sit strictly
    # between the central ridge window and the temporal hollowing windows,
    # or "exclude the ridge and extreme temporal portions from the fit"
    # (see the module docstring) doesn't actually hold.
    assert SHOULDER_INNER_U < TEMPORAL_INNER_U
    assert TEMPORAL_INNER_U < TEMPORAL_OUTER_U


# --- sharing the HC slice height between cranial and facial frames -------


def test_hc_slice_height_facial_frame_matches_direct_cranial_computation():
    mesh, landmarks = _ellipsoid_with_landmarks()

    cranial_reg = register(mesh, landmarks, target="cranium", com_translation=True)
    direct_cranial_height = find_hc_slice_height(cranial_reg.mesh, cranial_reg.landmarks)

    face_reg = register(mesh, landmarks, target="face", com_translation=True)
    reconstructed = hc_slice_height_facial_frame(face_reg)

    # both registrations are deterministic (quadric decimation, no RNG) and
    # start from the same landmarks/com_translation, so the sellion offset
    # face_reg applied internally should be exactly cranial_reg.landmarks[0]
    expected = direct_cranial_height - cranial_reg.landmarks[0][1]
    assert reconstructed == pytest.approx(expected, abs=1e-6)


def test_hc_slice_height_facial_frame_requires_a_face_target_registration():
    mesh, landmarks = _ellipsoid_with_landmarks()
    cranial_reg = register(mesh, landmarks, target="cranium", com_translation=True)
    with pytest.raises(ValueError):
        hc_slice_height_facial_frame(cranial_reg)
