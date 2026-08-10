"""cephalometric measurements - OFD, BPD, cephalic index, circumference, volume.

this is a rewrite of the old CranioMetrics class (craniometrics/craniometrics.py
in the legacy branch) using trimesh instead of pyvista. pyvista's .slice()/.bounds
became trimesh's .section(), and I dropped the pandas dataframe stuff (it was
just being used as a fancy list, and .append() got removed in pandas 2 anyway so
the old code was broken on anything but pandas 1.3.3).

this is the validated part of the app (see the README citations), so don't touch
the slicing/measurement math without rerunning it against
tests/fixtures/test_mesh_craniometrics_baseline.json first.

found a weird one while porting: in the old code, if the first max-depth slice's
circumference comes out over 60cm, it searches upward for a slice under 60cm and
uses THAT for the reported circumference - but then goes back and computes
depth/breadth/CI/the four landmark points at the ORIGINAL slice height, not the
one it just found. so if that branch ever actually fires, circumference and
everything else describe two different heights. left it exactly as-is (see
below), probably never got noticed because it's basically never triggered on
kids' heads. flagging it here in case it matters later.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from .remesh import repair_mesh


@dataclass
class SliceProfile:
    y: float
    depth: float
    breadth: float
    x_min: float
    x_max: float
    z_min: float
    z_max: float


@dataclass
class CranioMeasurements:
    slice_height: float
    depth_mm: float
    breadth_mm: float
    cephalic_index: float
    circumference_cm: float
    mesh_volume_cc: float
    front_opt: np.ndarray
    occ_opt: np.ndarray
    lh_opt: np.ndarray
    rh_opt: np.ndarray


def _slice_points(mesh: trimesh.Trimesh, y: float) -> np.ndarray | None:
    """points where the mesh crosses the plane y=const. None if the plane misses it."""
    section = mesh.section(plane_normal=[0, 1, 0], plane_origin=[0, y, 0])
    if section is None or len(section.vertices) == 0:
        return None
    return np.asarray(section.vertices)


def _profile(pts: np.ndarray, y: float) -> SliceProfile:
    x_min, x_max = float(pts[:, 0].min()), float(pts[:, 0].max())
    z_min, z_max = float(pts[:, 2].min()), float(pts[:, 2].max())
    return SliceProfile(
        y=y,
        depth=round(z_max - z_min, 2),
        breadth=round(x_max - x_min, 2),
        x_min=x_min, x_max=x_max,
        z_min=z_min, z_max=z_max,
    )


def _scan_slices(mesh: trimesh.Trimesh, slice_d: int = 1) -> list[SliceProfile]:
    """horizontal slices from y=0 up to the top of the mesh. starts at 0, not the
    mesh's actual min y, same as the original - registration already puts the
    head in a consistent spot relative to y=0 so this is fine."""
    y_max = int(np.ceil(mesh.bounds[1][1]))
    profiles: list[SliceProfile] = []
    for y in range(0, y_max, slice_d):
        pts = _slice_points(mesh, y)
        profiles.append(_profile(pts, y) if pts is not None else SliceProfile(y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    return profiles


def _ear_clear_mask(profiles: list[SliceProfile], min_y: float, ear_clear_fraction: float) -> np.ndarray:
    """boolean mask, True for slices at/above min_y that have cleared the
    ear-width plateau - see _select_slice_index's docstring for the
    reasoning. real ears show up as a distinct plateau in the breadth
    profile (steadily wide while the slice is still cutting through pinna
    cartilage), ending in a sharp drop once the slice clears the top of the
    ear and the profile is just head again - a real scan went 155mm ->
    135mm breadth over 3mm of height right at that boundary. so above
    min_y, find the highest breadth in that zone (the ear bulge peak) and
    require ear_clear_fraction of it before a slice counts as past the
    ears - a direct read of where THIS head's ears actually end, rather
    than a guessed-at margin that has to somehow work for every ear shape
    and every age. falls back to the plain min_y mask if nothing looks
    cleared (no obvious bulge to clear)."""
    ys = np.array([p.y for p in profiles])
    breadths = np.array([p.breadth for p in profiles])
    eligible = ys >= min_y
    if not eligible.any():
        return eligible

    peak_idx = int(np.argmax(np.where(eligible, breadths, -np.inf)))
    peak_breadth = breadths[peak_idx]
    cleared_ears = breadths <= peak_breadth * ear_clear_fraction
    cleared_ears[:peak_idx] = False  # only look for the drop-off after the peak
    past_ears = eligible & cleared_ears
    return past_ears if past_ears.any() else eligible


def _select_slice_index(
    profiles: list[SliceProfile],
    slice_d: int = 1,
    breadth_limit: float = 180.0,
    min_y: float | None = None,
    ear_clear_fraction: float = 0.9,
) -> int:
    """find the deepest slice, but skip past ones with breadth >180mm - those are
    almost always ears sticking out rather than actual head width.

    breadth_limit alone isn't reliable on its own: it's an absolute mm value,
    so a small/pediatric head can have its ears included in the breadth and
    still land under 180mm, and the loop below would never trigger - the
    slice search just keeps whatever ear-level slice happened to be deepest.
    min_y (when given - see extract_measurements) is where _ear_clear_mask
    starts looking for the ears in the first place."""
    depths = np.array([p.depth for p in profiles])

    if min_y is not None:
        eligible = _ear_clear_mask(profiles, min_y, ear_clear_fraction)
        if eligible.any():
            depths = np.where(eligible, depths, -np.inf)
    index = int(np.argmax(depths))

    count = 0
    while profiles[index].breadth >= breadth_limit and count <= 100:
        count += 1
        index += slice_d
        if index >= len(profiles):
            # the old code just let this IndexError out. clamping here instead so
            # it doesn't crash - doesn't change any actual measurement, just avoids
            # blowing up if we somehow walk off the end of the slice list.
            index = len(profiles) - 1
            break
    return index


def hc_slice_polygon(mesh: trimesh.Trimesh, y: float) -> np.ndarray | None:
    """the head-circumference slice as a closed loop (points sorted by angle
    around the center) - this is the red line the old app used to draw for the
    HC measurement. None if the plane doesn't hit the mesh at all."""
    pts = _slice_points(mesh, y)
    if pts is None:
        return None
    phi = np.arctan2(pts[:, 2], pts[:, 0])
    return pts[np.argsort(phi)]


def _circumference_cm(mesh: trimesh.Trimesh, y: float) -> float:
    """head circumference at height y. sorts the slice points by angle then sums
    up the chord distance between neighbors - same approximation the old app used,
    not a true arc length but close enough."""
    pts = hc_slice_polygon(mesh, y)
    if pts is None:
        return 0.0

    rho = np.hypot(pts[:, 0], pts[:, 2])
    phi = np.arctan2(pts[:, 2], pts[:, 0])

    rho1, rho2 = rho[:-1], rho[1:]
    phi1, phi2 = phi[:-1], phi[1:]
    chord = np.sqrt(np.clip(rho1 ** 2 + rho2 ** 2 - 2 * rho1 * rho2 * np.cos(phi1 - phi2), 0, None))
    return round(float(chord.sum()) / 10, 1)


def _watertight_volume_cc(mesh: trimesh.Trimesh) -> float:
    """mesh.volume only means anything for a watertight mesh, and the
    harmonized mesh handed to extract_measurements is intentionally left open
    where it got clipped (see clipping.py) - so cap a throwaway copy just for
    this one number instead of touching the mesh we actually return/export.

    uses the same pymeshfix repair the pipeline itself uses for real holes -
    tried trimesh's own fill_holes here first but it couldn't even close the
    plain neck opening on the shipped head template, let alone a messier
    clip boundary. falls back to 0.0 if even that can't get it watertight -
    better an honest 0 than a volume number computed on an open surface."""
    if mesh.is_watertight:
        return round(mesh.volume / 1000, 2)
    capped = repair_mesh(mesh, method="pymeshfix")
    if not capped.is_watertight:
        return 0.0
    return round(capped.volume / 1000, 2)


def _circumference_search(mesh: trimesh.Trimesh, slice_height: float, slice_d: int, max_iterations: int) -> float:
    """walks upward looking for a slice under 60cm circumference. this is a
    straight port of the old recursion into a loop - and yeah, the height it
    lands on here does NOT get used for the other measurements below, see the
    module docstring for why that's weird."""
    height = slice_height
    hc = _circumference_cm(mesh, height)
    steps = 0
    while hc > 60 and steps < max_iterations:
        height += slice_d
        hc = _circumference_cm(mesh, height)
        steps += 1
    return hc


def extract_measurements(
    mesh: trimesh.Trimesh,
    slice_d: int = 1,
    max_hc_search: int = 200,
    landmarks: np.ndarray | None = None,
    ear_safety_margin_mm: float = 5.0,
    ear_clear_fraction: float = 0.9,
) -> CranioMeasurements:
    """OFD/BPD/CI/circumference/volume for an already-registered mesh. same as
    CranioMetrics.slice_mesh + extract_dimensions combined.

    landmarks (optional, [nasion, left_tragus, right_tragus] in this mesh's
    own frame) rules out picking a slice at ear level: nothing at or below
    max(left_tragus.y, right_tragus.y) + ear_safety_margin_mm is eligible
    at all (the tragus landmarks themselves, plus a small buffer), and
    above that, _select_slice_index looks for where breadth actually drops
    off the ear-width plateau (see its docstring - ear_clear_fraction is
    just threaded through to there). left out (None) entirely preserves
    the old breadth-only behavior - the regression baseline in
    tests/fixtures never had landmarks to give it in the first place,
    since it runs on a raw, unregistered mesh."""
    min_y = None
    if landmarks is not None:
        landmarks = np.asarray(landmarks)
        min_y = float(max(landmarks[1][1], landmarks[2][1])) + ear_safety_margin_mm

    profiles = _scan_slices(mesh, slice_d)
    index = _select_slice_index(profiles, slice_d, min_y=min_y, ear_clear_fraction=ear_clear_fraction)
    slice_height = profiles[index].y

    hc = _circumference_search(mesh, slice_height, slice_d, max_hc_search)

    pts = _slice_points(mesh, slice_height)
    if pts is None:
        raise ValueError(f"No mesh intersection at the selected slice height y={slice_height}")
    profile = _profile(pts, slice_height)

    ci = round(100 * (profile.breadth / profile.depth), 1) if profile.depth else 0.0

    lh_opt = pts[pts[:, 0] == profile.x_min][0]
    rh_opt = pts[pts[:, 0] == profile.x_max][0]
    occ_opt = pts[pts[:, 2] == profile.z_min][0]
    front_opt = pts[pts[:, 2] == profile.z_max][0]

    return CranioMeasurements(
        slice_height=slice_height,
        depth_mm=profile.depth,
        breadth_mm=profile.breadth,
        cephalic_index=ci,
        circumference_cm=hc,
        mesh_volume_cc=_watertight_volume_cc(mesh),
        front_opt=front_opt,
        occ_opt=occ_opt,
        lh_opt=lh_opt,
        rh_opt=rh_opt,
    )


def slice_center_of_mass(
    mesh: trimesh.Trimesh, slice_height: float | None = None, landmarks: np.ndarray | None = None
) -> np.ndarray:
    """plain average of the slice points at slice_height (auto-detects the
    HC slice if you don't pass one in - see extract_measurements's landmarks
    param for what that does with them).

    this is what the old com_translation / cranial_cut CoM step used
    (CranioMetrics(...).HC_s.center_of_mass() - just an unweighted mean since a
    bare slice has no faces to weight by). same computation, used in a couple
    different places in the pipeline with different bits of the result applied.
    """
    if slice_height is None:
        slice_height = extract_measurements(mesh, landmarks=landmarks).slice_height
    pts = _slice_points(mesh, slice_height)
    if pts is None:
        raise ValueError(f"No mesh intersection at y={slice_height}")
    return pts.mean(axis=0)
