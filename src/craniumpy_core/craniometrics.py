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


def _select_slice_index(
    profiles: list[SliceProfile],
    slice_d: int = 1,
    breadth_limit: float = 180.0,
    min_y: float | None = None,
) -> int:
    """find the deepest slice, but skip past ones with breadth >180mm - those are
    almost always ears sticking out rather than actual head width.

    breadth_limit alone isn't reliable on its own: it's an absolute mm value,
    so a small/pediatric head can have its ears included in the breadth and
    still land under 180mm, and the loop below would never trigger - the
    slice search just keeps whatever ear-level slice happened to be deepest.
    min_y (when given - see extract_measurements) is a hard floor at
    tragus-height-plus-margin that rules out anything at or below ear-canal
    level.

    used to also have a fancier breadth-plateau heuristic on top of min_y,
    looking for a 90%-of-peak drop in breadth to catch ears that stay under
    the 180mm limit. dropped it - it assumes ear breadth drops off sharply
    once you're past the pinna, but a head whose natural widest point (the
    parietal eminence, well above the ears) is nearly as wide as the ears
    themselves breaks that assumption completely: found on a real scan
    where it chased the 90%-of-peak drop all the way up near the crown,
    since breadth never dropped that far until then. min_y alone is a
    blunter tool but a much more reliable one - it can't be fooled by head
    shape the way a breadth threshold can."""
    depths = np.array([p.depth for p in profiles])

    if min_y is not None:
        ys = np.array([p.y for p in profiles])
        eligible = ys >= min_y
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


def find_hc_slice_height(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray | None = None,
    slice_d: int = 1,
    ear_safety_margin_mm: float = 5.0,
) -> float:
    """just the "which height is the HC slice" search, factored out of
    extract_measurements so metopic.py's facial-frame reconstruction (see
    pipeline.hc_slice_height_facial_frame) can reuse the exact same search
    without pulling in the rest of extract_measurements's cranial-only
    circumference/BPD/OFD machinery. extract_measurements below calls this
    internally - same landmarks/ear-avoidance behavior described there.

    intentionally doesn't do the >60cm circumference re-search
    (_circumference_search) - that's a circumference-reporting quirk (see
    this module's docstring), not part of "which height is the HC slice"."""
    min_y = None
    if landmarks is not None:
        landmarks = np.asarray(landmarks)
        min_y = float(max(landmarks[1][1], landmarks[2][1])) + ear_safety_margin_mm

    profiles = _scan_slices(mesh, slice_d)
    index = _select_slice_index(profiles, slice_d, min_y=min_y)
    return profiles[index].y


def extract_measurements(
    mesh: trimesh.Trimesh,
    slice_d: int = 1,
    max_hc_search: int = 200,
    landmarks: np.ndarray | None = None,
    ear_safety_margin_mm: float = 5.0,
) -> CranioMeasurements:
    """OFD/BPD/CI/circumference/volume for an already-registered mesh. same as
    CranioMetrics.slice_mesh + extract_dimensions combined.

    landmarks (optional, [sellion, left_tragus, right_tragus] in this mesh's
    own frame) rules out picking a slice at ear level: nothing at or below
    max(left_tragus.y, right_tragus.y) + ear_safety_margin_mm is eligible
    at all (the tragus landmarks themselves, plus a small buffer) - see
    _select_slice_index's docstring for why that's the only ear-avoidance
    left. left out (None) entirely preserves the old breadth-only behavior
    - the regression baseline in tests/fixtures never had landmarks to
    give it in the first place, since it runs on a raw, unregistered
    mesh."""
    slice_height = find_hc_slice_height(mesh, landmarks, slice_d, ear_safety_margin_mm)

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


@dataclass
class FrontalBossingResult:
    angle_deg: float
    sellion: np.ndarray  # (3,)
    frontal_point: np.ndarray  # (3,) - the forehead point at the HC slice height, above sellion
    profile: np.ndarray  # (N, 3) the sagittal (midline) contour, for drawing
    # unit vector for "horizontal" - the direction angle_deg was actually
    # measured against. always +z in the frame the angle was computed in
    # (see frontal_bossing below), but a display frame reached via a
    # secondary frontal landmark is rotated relative to that frame, so
    # anything DRAWING this construction in another frame needs the rotated
    # direction rather than that frame's own +z (see
    # pipeline.measure_cranial). kept here rather than recomputed by each
    # consumer so the drawn reference line can't disagree with the number.
    horizontal: np.ndarray = None  # type: ignore[assignment]
    # the y (height) frontal_point was anchored to - the same height the
    # head-circumference/OFD/BPD slice uses (see extract_measurements),
    # threaded through purely so a consumer (the exported figure) can draw
    # it as an explicit reference without recomputing anything. carried
    # along, not re-derived, for the same reason horizontal is: nothing
    # should be able to draw a value that disagrees with what angle_deg was
    # actually measured against.
    slice_height: float = 0.0

    def __post_init__(self) -> None:
        if self.horizontal is None:
            self.horizontal = np.array([0.0, 0.0, 1.0])


def _ordered_sagittal_profile(section) -> np.ndarray:
    """the longest connected piece of a mesh cross-section, in its own
    connectivity order - same technique metopic.forehead_contour uses for
    the horizontal HC slice, applied here to a vertical sagittal one.
    mesh.section()'s own .vertices is just an unordered point soup; a
    single mesh entity's own .discrete(vertices) walks it in actual
    surface order, which is what a clean single line needs. returns an
    empty (0, 3) array if the section has nothing to walk."""
    if section is None or len(section.entities) == 0:
        return np.empty((0, 3))
    pieces = [e.discrete(section.vertices) for e in section.entities]
    pieces = [p for p in pieces if len(p) > 0]
    if not pieces:
        return np.empty((0, 3))
    return max(pieces, key=len)


def _forehead_point_at_slice_height(arc: np.ndarray, slice_height: float) -> np.ndarray:
    """where the forehead arc (the "above sellion" run of the sagittal
    profile, already ordered walking away from sellion) crosses
    y = slice_height, by linear interpolation between the two straddling
    points. falls back to the arc's own most anterior (max z) point if
    slice_height sits outside the arc's y range at all (an unusually
    short/tall scan where the HC height doesn't actually land on this
    person's forehead) - same fallback the old argmax-only version always
    used, so this only ever degrades to the previous behavior rather than
    raising."""
    y = arc[:, 1]
    if y[0] > y[-1]:
        arc = arc[::-1]
        y = y[::-1]
    if slice_height <= y[0] or slice_height >= y.max():
        return arc[np.argmax(arc[:, 2])]
    idx = int(np.argmax(y >= slice_height))  # first index at/above slice_height
    p0, p1 = arc[idx - 1], arc[idx]
    t = (slice_height - p0[1]) / (p1[1] - p0[1])
    return p0 + t * (p1 - p0)


def _select_forehead_half(arc: np.ndarray, sellion: np.ndarray) -> np.ndarray:
    """picks the actual forehead-to-vertex piece out of the full
    above-sellion sagittal arc, which on a real (closed-cap) cranial/facial
    mesh doesn't stop at the vertex - it keeps going in one unbroken sweep
    down the OTHER side too, so both the forehead's base near sellion AND
    the occiput's base near the back of the head end up "above sellion" and
    get walked as a single contiguous run (see frontal_bossing's own
    above_mask/arc selection above this).

    _forehead_point_at_slice_height used to just trust whichever end of
    that combined arc came first in mesh.section()'s own traversal order
    (flipped only by comparing the two ends' y - both of which sit near
    sellion's height, so which one happens to be a hair higher is
    essentially arbitrary jitter from resampling/decimation, not a real
    front/back signal) - meaning it could silently walk from the occiput
    end and report an occipital point as the "forehead" one. reported as:
    the same landmarks giving a correct frontal-bossing angle on one run
    and a clearly-wrong one (pointing at the back of the head) on another,
    depending on nothing the user changed.

    splits the arc at its own highest point (the vertex/crown - the one
    unambiguous landmark on it) into its two monotonic halves, then keeps
    whichever half's low-y (near-sellion-height) endpoint sits closer to
    sellion in z. that's a real anatomical signal instead of arbitrary
    ordering: the forehead's base is right next to sellion, while the
    occiput's base is clear across the head. returns the kept half ordered
    ascending in y (low endpoint first, vertex last) - already exactly what
    _forehead_point_at_slice_height's own walk expects, so its own
    y[0] > y[-1] flip is a no-op on this input, just a harmless safety net.
    """
    crown_idx = int(np.argmax(arc[:, 1]))
    front_half = arc[: crown_idx + 1]
    back_half = arc[crown_idx:][::-1]
    front_dz = abs(front_half[0, 2] - sellion[2])
    back_dz = abs(back_half[0, 2] - sellion[2])
    return front_half if front_dz <= back_dz else back_half


def frontal_bossing(mesh: trimesh.Trimesh, sellion: np.ndarray, slice_height: float) -> FrontalBossingResult | None:
    """how much the forehead bulges forward, measured in the sagittal
    (midline) plane through sellion: slices the mesh at x = sellion.x,
    then reports the angle between horizontal (the z-axis, through
    sellion) and the vector from sellion to wherever that sagittal profile
    crosses y = slice_height on the forehead side (y > sellion.y,
    restricted to the forehead rather than the nose/lips/chin below
    sellion, which would otherwise be picked up on a facial-target mesh
    that still has a nose on it).

    slice_height is the same height extract_measurements chose for the
    head-circumference/OFD/BPD slice (see CranioMeasurements.slice_height)
    - anchoring the bossing angle's second point to that shared reference
    plane, rather than to an independently found local maximum, is what
    keeps it comparable to those measurements and reproducible: the old
    "most anterior point above sellion" approach could land on whatever
    local bump happened to stick out furthest (a brow ridge, a stray
    scanning artifact), not necessarily anything anatomically tied to the
    rest of the report.

    a forehead that bulges mostly straight out before curving up reads as
    a small angle (close to 0, near-horizontal - a prominent/bossed
    forehead); one that goes mostly straight up with little forward
    bulge reads as a large angle (close to 90, near-vertical - a flatter
    or receding forehead). works the same in either registered frame
    (cranial or facial), since it's defined purely relative to sellion's
    own position. None if the plane misses the mesh, or nothing on it
    sits above sellion at all.

    the given sellion is snapped onto this mesh's own surface before
    anything else. the landmark comes from a click on the RAW scan, while
    this mesh has since been repaired, clipped and resampled - and quadric
    decimation pulls a tight concavity like the nasal root slightly inward,
    which leaves the original pick sitting a millimetre or two off the
    surface in front of it. that showed up as a visible gap between the
    drawn sellion marker and the mesh, and it also means the angle's own
    origin wasn't quite on the surface the rest of the construction (the
    section, the frontal point) was taken from. snapping fixes both, and
    makes the value independent of how far decimation happened to move
    that spot.
    """
    sellion = np.asarray(sellion, dtype=np.float64)
    snapped, _, _ = trimesh.proximity.closest_point(mesh, sellion[np.newaxis, :])
    sellion = snapped[0]

    section = mesh.section(plane_normal=[1, 0, 0], plane_origin=[sellion[0], 0, 0])
    if section is None or len(section.vertices) == 0:
        return None

    pts = np.asarray(section.vertices)
    ordered = _ordered_sagittal_profile(section)
    profile = ordered if len(ordered) else pts

    above_mask = profile[:, 1] > sellion[1]
    if not above_mask.any():
        return None

    # the largest contiguous run of "above sellion" indices along the
    # ordered walk - the actual forehead-to-vertex arc, in case the above-
    # sellion mask also catches an unrelated sliver elsewhere on the
    # profile (e.g. the far side of the head, on a full facial mesh).
    indices = np.where(above_mask)[0]
    splits = np.where(np.diff(indices) > 1)[0] + 1
    arc = profile[max(np.split(indices, splits), key=len)]
    arc = _select_forehead_half(arc, sellion)

    frontal_point = _forehead_point_at_slice_height(arc, slice_height)
    dy = frontal_point[1] - sellion[1]
    dz = frontal_point[2] - sellion[2]
    angle_deg = float(np.degrees(np.arctan2(dy, dz)))

    return FrontalBossingResult(
        angle_deg=angle_deg,
        sellion=sellion,
        frontal_point=frontal_point,
        profile=profile,
        horizontal=np.array([0.0, 0.0, 1.0]),
        slice_height=float(slice_height),
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
