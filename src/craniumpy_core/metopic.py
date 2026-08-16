"""frontal-angle / metopic shape analysis, computed on the 2D forehead
contour taken from the exact same HC-slice height cranial analysis uses -
see pipeline.hc_slice_height_facial_frame for how that height gets shared
between the cranial and facial pipelines, and craniometrics.py's module
docstring for why the HC slice itself is treated as validated, careful code.

there's no clinical ground-truth baseline for any of this the way
craniometrics.py has one (tests/fixtures/test_mesh_craniometrics_baseline.json)
- this is new math with no real trigonocephaly scan to check it against, so
tests/test_metopic.py validates against synthetic contours with known shapes
instead (a flat/rounded one, one with an added central bump, one with added
lateral dips) rather than a numeric golden file. the region-window constants
below are the most likely thing to need retuning once real scans exist to
check against - kept as named constants for exactly that reason, not folded
into the math.

the "ideal parabola" every deviation-based quantity here is measured against
(deviation_profile, ridge_protrusion_mm, ridge_area_mm2, the temporal
hollowing metrics, parabolic_deviation_index) is fit to THIS patient's own
forehead - specifically the "shoulder" windows just outside the central
ridge (SHOULDER_INNER_U..SHOULDER_OUTER_U, both sides of the midline), not
to any healthy-population reference. that makes every one of those numbers
self-referential, not a deviation-from-normal: a real forehead, healthy or
not, was never exactly a parabola to begin with, so "near zero" means "this
forehead's center matches what its own flanks predict," not "this forehead
is normal." and if the condition being measured also distorts the flanks
(not just the center), the fit inherits that distortion too - the reported
deviation then reads as "more localized to the center than the rest of this
forehead already is," not "abnormal" in any absolute sense. how much that
matters in practice - i.e. how confined a given condition actually stays to
the center versus how far it reaches into the shoulder windows - isn't
something this module can answer without real scans to check against.

axis convention: this module works in the same 2D plane the forehead
contour lives in (the mesh's own x/z at a fixed y = slice height) - x is
left-right (same sign convention as asymmetry.py's _half_mask: x<0 left,
x>0 right), z is depth/anterior-posterior (increasing z = more anterior,
same convention craniometrics.py's front_opt/occ_opt already use - front_opt
is the z_max point, occ_opt is z_min). the original spec this was written
from calls the depth axis "y" in its own local 2D notation - every place
below that maps to a formula from that spec, it's this z, not the mesh's
actual height axis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.optimize import least_squares

# region windows, expressed as fractions of normalized arc length u = s/S,
# centered on u0 (the midline - where the contour crosses x=0, found by
# interpolation, not assumed to be the arc's exact midpoint). all of these
# are provisional engineering defaults, not clinical values - the spec this
# was built from explicitly leaves them "predefined" without numbers and
# says not to hardcode clinically meaningful weights at this stage (kept
# modular so they can be retuned once real scans are available to check
# against, same as this module's docstring above).
CENTRAL_WINDOW_HALF_WIDTH_U = 0.12  # the metopic ridge window C
SHOULDER_INNER_U = 0.15  # parabola-fit windows: u0 +/- [INNER, OUTER], both sides
SHOULDER_OUTER_U = 0.35
TEMPORAL_INNER_U = 0.35  # temporal hollowing windows T_L/T_R: u0 +/- [INNER, OUTER]
TEMPORAL_OUTER_U = 0.48
FRONTAL_ANGLE_HALF_WIDTH_U = 0.30  # L/R frontal-angle points: u0 +/- this
SMOOTHING_WINDOW = 5  # points, light moving-average before any derivative

# M (the ridge-protrusion point/marker) is the most anterior (max z) point
# within this fixed +/-mm window of the midline (x=0) - a physical window,
# not an arc-length one like the windows above, since "the most forward
# point of the forehead" is a location on the actual contour, not a
# fraction of its fitted-parabola-relative deviation. deliberately doesn't
# reuse CENTRAL_WINDOW_HALF_WIDTH_U - that window (in u) is about
# integrating curvature/deviation over the ridge REGION for MCC/ridge_area,
# a different question from "where is the single apex point."
RIDGE_APEX_X_WINDOW_MM = 15.0


@dataclass
class MetopicResult:
    contour: np.ndarray  # (N, 2) smoothed forehead contour, columns (x, z)
    arc_length: np.ndarray  # (N,) cumulative s, from the smoothed contour
    normalized_arc_length: np.ndarray  # (N,) u = s / S
    midline_u: float  # u0 - where the contour crosses x=0

    parabola_a: float
    parabola_c: float
    deviation_profile: np.ndarray  # (N,) d_P(u), signed, mm
    gradient_profile: np.ndarray  # (N,) phi(u), radians
    curvature_profile: np.ndarray  # (N,) kappa(u), 1/mm, positive = outward convex

    frontal_angle_deg: float
    frontal_angle_points: tuple[np.ndarray, np.ndarray, np.ndarray]  # (M, L, R), each (x, z)
    forehead_width_mm: float  # W, |R - L|

    midline_curvature_concentration: float
    midline_max_curvature: float
    midline_max_curvature_position: float  # u

    ridge_protrusion_mm: float
    ridge_protrusion_position: float  # u
    # signed: positive means the central window sticks out past the ideal
    # parabola on net, negative means it falls short of it on net (a flat/
    # recessed center relative to what the shoulders imply) - see
    # analyze_forehead's own comment on ridge_area_mm2 below.
    ridge_area_mm2: float
    ridge_area_normalized: float

    left_temporal_hollowing: float
    right_temporal_hollowing: float
    mean_temporal_hollowing: float
    left_max_temporal_depth_mm: float
    right_max_temporal_depth_mm: float

    parabolic_deviation_index: float

    central_window: tuple[float, float]  # (u0 - half, u0 + half), for drawing
    left_temporal_window: tuple[float, float]
    right_temporal_window: tuple[float, float]


def forehead_contour(mesh: trimesh.Trimesh, slice_height: float) -> np.ndarray | None:
    """the forehead-only portion of the mesh's cross-section at slice_height,
    as an ordered (N, 2) array of (x, z) points, left to right. None if the
    plane misses the mesh, or the piece found doesn't actually cross x=0 (so
    isn't a genuine forehead-spanning arc - e.g. the slice landed above or
    below the facial-clipped mesh's actual extent).

    doesn't reuse craniometrics.hc_slice_polygon's angle-sort - that assumes
    a closed loop all the way around a full head. the facial-clipped mesh is
    an open patch (bounded by facial_clip's sphere trim), so its
    cross-section is one or more open polylines instead. Path3D.discrete
    only returns entities trimesh has grouped into *closed* paths, which
    silently drops an open cross-section entirely - each entity's own
    .discrete(vertices) still gives its ordered point sequence regardless,
    so entities are walked directly here and the longest one is taken as
    the forehead arc.
    """
    section = mesh.section(plane_normal=[0, 1, 0], plane_origin=[0, slice_height, 0])
    if section is None or len(section.entities) == 0:
        return None

    pieces = [e.discrete(section.vertices) for e in section.entities]
    pieces = [p for p in pieces if len(p) >= 5]
    if not pieces:
        return None
    longest = max(pieces, key=len)

    xz = np.column_stack([longest[:, 0], longest[:, 2]])
    x = xz[:, 0]
    if not (x.min() < 0.0 < x.max()):
        return None
    if x[0] > x[-1]:
        xz = xz[::-1]
    return xz


def _arc_length(points: np.ndarray) -> np.ndarray:
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _smooth(values: np.ndarray, window: int = SMOOTHING_WINDOW) -> np.ndarray:
    """plain centered moving average, edge-padded so the array length and
    endpoints don't shift - light enough to just take mesh/sampling noise
    off, not to reshape the actual ridge/hollow morphology (see this
    module's docstring for why that distinction matters here)."""
    if window <= 1 or len(values) < window:
        return values
    kernel = np.ones(window) / window
    pad = window // 2
    padded = np.pad(values, (pad, window - 1 - pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    """plain trapezoidal integration - a tiny local implementation instead
    of np.trapz/np.trapezoid, whose name/availability differs across the
    numpy versions this project's dependency range (numpy>=1.26) spans."""
    if len(x) < 2:
        return 0.0
    return float(np.sum((y[1:] + y[:-1]) / 2.0 * np.diff(x)))


def _find_midline_u(x: np.ndarray, u: np.ndarray) -> float:
    """u where the (already left-to-right, already known to cross x=0 - see
    forehead_contour) contour crosses the facial midline, linearly
    interpolated between the two bracketing points."""
    sign_changes = np.where(np.diff(np.sign(x)) != 0)[0]
    if len(sign_changes) == 0:
        return float(u[np.argmin(np.abs(x))])
    i = int(sign_changes[0])
    t = -x[i] / (x[i + 1] - x[i])
    return float(u[i] + t * (u[i + 1] - u[i]))


def _fit_parabola(x: np.ndarray, z: np.ndarray) -> tuple[float, float]:
    """robust least-squares fit of z = a*x^2 + c. f_scale (where soft_l1
    starts down-weighting outliers) comes from the plain-fit residuals' own
    robust spread (MAD) instead of a fixed mm value, so this doesn't need
    retuning for a different head size."""
    A = np.column_stack([x**2, np.ones_like(x)])
    a0, c0 = np.linalg.lstsq(A, z, rcond=None)[0]
    residuals0 = z - (a0 * x**2 + c0)
    scale = max(1.4826 * float(np.median(np.abs(residuals0 - np.median(residuals0)))), 1e-3)

    def residuals(params: np.ndarray) -> np.ndarray:
        a, c = params
        return z - (a * x**2 + c)

    result = least_squares(residuals, x0=[a0, c0], loss="soft_l1", f_scale=scale)
    return float(result.x[0]), float(result.x[1])


def _deviation_profile(x: np.ndarray, z: np.ndarray, a: float, c: float) -> np.ndarray:
    """signed distance from the contour to the parabola, in the parabola's
    local normal direction at each point's own x - a first-order
    approximation (vertical gap projected through the tangent angle) of the
    true nearest-point-on-curve normal distance, same spirit as
    craniometrics.py's own circumference approximation (chord sum instead
    of true arc length) - close enough for a shape-deviation signal, much
    simpler than solving for the true closest point on the parabola.
    positive = contour lies more anterior (larger z) than the parabola."""
    z_p = a * x**2 + c
    slope = 2 * a * x
    cos_theta = 1.0 / np.sqrt(1.0 + slope**2)
    return (z - z_p) * cos_theta


def _gradient_and_curvature(x: np.ndarray, z: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """phi(s) = atan2(z'(s), x'(s)), kappa(s) = (x'z'' - z'x'') / (x'^2+z'^2)^1.5,
    sign-flipped from the raw parametric formula so outward (anterior)
    convexity comes out positive, matching the sign convention the spec this
    was built from asks for - verified against a synthetic convex bump in
    tests/test_metopic.py, since the "natural" sign of this formula depends
    on which axis is x/y and which direction the contour is traversed, both
    fixed by this module's own conventions (see the module docstring)."""
    dx = np.gradient(x, s)
    dz = np.gradient(z, s)
    d2x = np.gradient(dx, s)
    d2z = np.gradient(dz, s)

    phi = np.arctan2(dz, dx)
    denom = np.power(dx**2 + dz**2, 1.5)
    denom = np.where(denom < 1e-9, 1e-9, denom)
    kappa = -(dx * d2z - dz * d2x) / denom
    return phi, kappa


def _window_mask(u: np.ndarray, u0: float, inner: float, outer: float, side: int) -> np.ndarray:
    """side=-1 for the window left of u0 (u0-outer..u0-inner), side=+1 for
    the window right of u0 (u0+inner..u0+outer)."""
    if side < 0:
        return (u >= u0 - outer) & (u <= u0 - inner)
    return (u >= u0 + inner) & (u <= u0 + outer)


def analyze_forehead(mesh: trimesh.Trimesh, slice_height: float) -> MetopicResult | None:
    """the whole metopic analysis, from a mesh + the shared HC slice height
    down to every value api.schemas.MetopicResponse needs. None wherever
    forehead_contour is (plane missed the mesh, or the slice at this height
    isn't a genuine forehead-spanning arc for this patient's facial clip)."""
    raw = forehead_contour(mesh, slice_height)
    if raw is None:
        return None

    x = _smooth(raw[:, 0])
    z = _smooth(raw[:, 1])
    s = _arc_length(np.column_stack([x, z]))
    total_length = float(s[-1])
    if total_length < 1e-6:
        return None
    u = s / total_length
    u0 = _find_midline_u(x, u)

    central_mask = (u >= u0 - CENTRAL_WINDOW_HALF_WIDTH_U) & (u <= u0 + CENTRAL_WINDOW_HALF_WIDTH_U)
    left_shoulder = _window_mask(u, u0, SHOULDER_INNER_U, SHOULDER_OUTER_U, side=-1)
    right_shoulder = _window_mask(u, u0, SHOULDER_INNER_U, SHOULDER_OUTER_U, side=1)
    shoulder_mask = left_shoulder | right_shoulder
    # fallback for a short/narrow contour where the shoulder windows come up
    # too sparse to fit against - just use everything outside the central
    # ridge window instead of failing the whole analysis.
    if shoulder_mask.sum() < 4:
        shoulder_mask = ~central_mask
    if shoulder_mask.sum() < 4:
        return None

    a, c = _fit_parabola(x[shoulder_mask], z[shoulder_mask])
    deviation = _deviation_profile(x, z, a, c)
    phi, kappa = _gradient_and_curvature(x, z, s)

    apex_mask = np.abs(x) <= RIDGE_APEX_X_WINDOW_MM
    if apex_mask.any():
        apex_idx = np.where(apex_mask)[0]
        ridge_idx = int(apex_idx[np.argmax(z[apex_idx])])
    else:
        ridge_idx = int(np.argmin(np.abs(x)))
    M = np.array([x[ridge_idx], z[ridge_idx]])

    l_idx = int(np.argmin(np.abs(u - (u0 - FRONTAL_ANGLE_HALF_WIDTH_U))))
    r_idx = int(np.argmin(np.abs(u - (u0 + FRONTAL_ANGLE_HALF_WIDTH_U))))
    L = np.array([x[l_idx], z[l_idx]])
    R = np.array([x[r_idx], z[r_idx]])

    v1, v2 = L - M, R - M
    cos_theta = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12)
    frontal_angle_deg = float(np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))
    forehead_width_mm = float(np.linalg.norm(R - L))

    kappa_pos = np.clip(kappa, 0.0, None)
    mcc_den = _trapz(kappa_pos, s)
    mcc_num = _trapz(kappa_pos[central_mask], s[central_mask]) if central_mask.sum() > 1 else 0.0
    mcc = mcc_num / mcc_den if mcc_den > 1e-9 else 0.0
    if central_mask.any():
        kappa_max = float(kappa[central_mask].max())
        kappa_max_pos = float(u[central_mask][np.argmax(kappa[central_mask])])
    else:
        kappa_max, kappa_max_pos = 0.0, u0

    # ridge_idx always resolves to a real point (apex_mask's own fallback -
    # see above), unlike the central-window-only quantities below.
    ridge_protrusion_mm = float(deviation[ridge_idx])
    ridge_protrusion_position = float(u[ridge_idx])
    # signed net area between the contour and the ideal parabola across the
    # whole central window - NOT clipped to the protruding part only. an
    # earlier clipped ("protrusion-only") version read a flat 0 whenever a
    # patient's center sat below the parabola across the whole window (a
    # real, seen-in-practice case - a center recessed relative to what this
    # forehead's own shoulders predict, not merely "no ridge"), silently
    # losing that signal instead of reporting it with a negative sign the
    # way ridge_protrusion_mm already did.
    ridge_area_mm2 = _trapz(deviation[central_mask], s[central_mask]) if central_mask.sum() > 1 else 0.0
    ridge_area_normalized = ridge_area_mm2 / (forehead_width_mm**2) if forehead_width_mm > 1e-6 else 0.0

    left_temporal_mask = _window_mask(u, u0, TEMPORAL_INNER_U, TEMPORAL_OUTER_U, side=-1)
    right_temporal_mask = _window_mask(u, u0, TEMPORAL_INNER_U, TEMPORAL_OUTER_U, side=1)
    w_sq = forehead_width_mm**2 if forehead_width_mm > 1e-6 else None

    def _thi(mask: np.ndarray) -> float:
        if w_sq is None or mask.sum() < 2:
            return 0.0
        return _trapz(np.clip(-deviation[mask], 0.0, None), s[mask]) / w_sq

    def _max_depth(mask: np.ndarray) -> float:
        if not mask.any():
            return 0.0
        return float(np.clip(-deviation[mask], 0.0, None).max())

    left_temporal_hollowing = _thi(left_temporal_mask)
    right_temporal_hollowing = _thi(right_temporal_mask)
    mean_temporal_hollowing = (left_temporal_hollowing + right_temporal_hollowing) / 2.0
    left_max_temporal_depth_mm = _max_depth(left_temporal_mask)
    right_max_temporal_depth_mm = _max_depth(right_temporal_mask)

    pdi = float(np.sqrt(max(_trapz(deviation**2, s), 0.0) / total_length))

    return MetopicResult(
        contour=np.column_stack([x, z]),
        arc_length=s,
        normalized_arc_length=u,
        midline_u=u0,
        parabola_a=a,
        parabola_c=c,
        deviation_profile=deviation,
        gradient_profile=phi,
        curvature_profile=kappa,
        frontal_angle_deg=frontal_angle_deg,
        frontal_angle_points=(M, L, R),
        forehead_width_mm=forehead_width_mm,
        midline_curvature_concentration=float(mcc),
        midline_max_curvature=kappa_max,
        midline_max_curvature_position=kappa_max_pos,
        ridge_protrusion_mm=ridge_protrusion_mm,
        ridge_protrusion_position=ridge_protrusion_position,
        ridge_area_mm2=ridge_area_mm2,
        ridge_area_normalized=ridge_area_normalized,
        left_temporal_hollowing=left_temporal_hollowing,
        right_temporal_hollowing=right_temporal_hollowing,
        mean_temporal_hollowing=mean_temporal_hollowing,
        left_max_temporal_depth_mm=left_max_temporal_depth_mm,
        right_max_temporal_depth_mm=right_max_temporal_depth_mm,
        parabolic_deviation_index=pdi,
        central_window=(u0 - CENTRAL_WINDOW_HALF_WIDTH_U, u0 + CENTRAL_WINDOW_HALF_WIDTH_U),
        left_temporal_window=(u0 - TEMPORAL_OUTER_U, u0 - TEMPORAL_INNER_U),
        right_temporal_window=(u0 + TEMPORAL_INNER_U, u0 + TEMPORAL_OUTER_U),
    )
