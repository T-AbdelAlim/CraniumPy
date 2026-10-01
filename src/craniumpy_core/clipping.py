"""cutting the mesh down to just the cranium or just the face.

ported the geometry from gui_methods.py's cranial_cut/facial_clip (old repo),
swapping pyvista's .clip()/.clip_surface() for trimesh's slice_mesh_plane.
works on an already-registered mesh (see registration.rigid.landmark_align) -
the plane/sphere numbers below are in that registered frame, same numbers
the old app used, except the cranial boundary itself: the old app cut at a
hardcoded y=-21 regardless of where the landmarks actually landed, which in
practice cut well below the sellion-tragus plane. cranial_clip now cuts
through the actual registered landmark plane instead - see landmark_plane.

double checked the sign convention rather than just assuming it: trimesh's
slice_mesh_plane(mesh, plane_normal=n) keeps the +n side by default, same as
pyvista's .clip(normal=n, invert=False). so old invert=False calls map
straight across to clip_plane(normal=n), invert=True becomes
clip_plane(normal=n, invert=True) which just flips to -n under the hood.

clips are left open (cap=False) same as before - the old app relied on a
separate repair step to close whatever holes this leaves, and so does this
(see remesh.repair_mesh, called from pipeline.harmonize).

the old app actually clipped, saved, repaired, resampled, reloaded, then did
a SECOND more precise clip pass. that whole dance is pipeline-level stuff now
(see pipeline.harmonize), not something baked into this file - these are just
the raw geometry ops, composable however the pipeline wants to use them.
manual clipping (user-picked plane) just calls clip_plane() directly too,
nothing special needed here for that.

one thing I didn't bother porting: the old cranial_cut computed a
`template_mesh` scaled by the ICV ratio and then never used it for anything.
dead code, checked the whole function to be sure.
"""

from __future__ import annotations

import numpy as np
import trimesh
from trimesh.intersections import slice_mesh_plane

from .remesh import clean_boundary, keep_largest_component

# the fixed numbers cranial_clip/facial_clip cut with, named here rather than
# written inline at the call sites so clip_preview_geometry below reports
# exactly what the real cut uses. the preview is drawn in the viewer as "this
# is what preprocessing will remove" (see three/clipPreviewOverlay.js), so the
# two drifting apart would quietly turn it into a lie - a second copy of these
# numbers in the frontend is precisely what this avoids.
CRANIAL_TRIM_SPHERE_CENTER = (0.0, 40.0, 0.0)
CRANIAL_TRIM_SPHERE_RADIUS = 175.0
CRANIAL_REAR_NECK_PLANE_NORMAL = (0.0, 0.6, 1.0)
CRANIAL_REAR_NECK_PLANE_ORIGIN = (0.0, -60.0, -50.0)

FACIAL_DEPTH_PLANE_NORMAL = (0.0, 0.0, 1.0)
FACIAL_TRIM_SPHERE_CENTER = (0.0, 25.0, -25.0)
# scaled off this patient's own inter-tragus distance - see facial_clip.
FACIAL_TRIM_SPHERE_RADIUS_FACTOR = 1.7


def adjusted_trim_sphere(center, radius: float, center_offset=None, radius_override: float | None = None):
    """the trim sphere after whatever the user moved or resized it to in
    the viewer ("adjust clipping sphere", see three/clipPreviewOverlay.js).

    None for both - what every non-interactive caller passes - leaves the
    tuned default exactly as it was. center_offset is a displacement in the
    registered frame; radius_override replaces the radius outright, in mm,
    since the two targets' defaults are arrived at differently (a fixed
    175mm for the cranium, a multiple of this patient's inter-tragus
    distance for the face) and a shared scale factor would mean something
    different on each."""
    center = np.asarray(center, dtype=np.float64)
    if center_offset is not None:
        center = center + np.asarray(center_offset, dtype=np.float64)
    if radius_override is not None:
        radius = float(radius_override)
    return center, float(radius)


def clip_plane(mesh: trimesh.Trimesh, normal, origin, invert: bool = False) -> trimesh.Trimesh:
    """keeps the half of the mesh on the +normal side of origin (or -normal if invert)."""
    n = np.asarray(normal, dtype=np.float64)
    if invert:
        n = -n
    return slice_mesh_plane(mesh, plane_normal=n, plane_origin=origin, cap=False)


def clip_sphere(mesh: trimesh.Trimesh, center, radius: float, keep_inside: bool = True) -> trimesh.Trimesh:
    """drops whole faces outside (or inside) a sphere. this is a rough trim, not
    a real geometric boolean against the sphere surface - faces that straddle
    the boundary just get kept or dropped whole rather than cut and
    re-triangulated like pyvista's clip_surface would do. that's fine though,
    this is only ever used to strip stray scan junk far from the head, not for
    an actual anatomical boundary (clip_plane handles that)."""
    center = np.asarray(center, dtype=np.float64)
    vertex_in = np.linalg.norm(mesh.vertices - center, axis=1) <= radius
    if keep_inside:
        face_mask = vertex_in[mesh.faces].all(axis=1)
    else:
        face_mask = ~vertex_in[mesh.faces].any(axis=1)
    face_indices = np.nonzero(face_mask)[0]
    return mesh.submesh([face_indices], append=True)


def landmark_plane(landmarks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """normal + origin of the plane through the 3 registered landmarks
    (sellion, left_tragus, right_tragus), oriented so +normal points toward
    the top of the head - flips the cross product if it doesn't, since
    landmark order alone doesn't guarantee a consistent winding.

    public (not just an internal step of cranial_clip below) since
    pipeline.rough_bounding_clip needs the exact same plane cranial_clip's
    real cut uses, to size its own margin off it."""
    landmarks = np.asarray(landmarks, dtype=np.float64)
    origin = landmarks.mean(axis=0)
    normal = np.cross(landmarks[1] - landmarks[0], landmarks[2] - landmarks[0])
    normal = normal / np.linalg.norm(normal)
    if normal[1] < 0:
        normal = -normal
    return normal, origin


def cranial_clip(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    trim_rear_neck: bool = True,
    sphere_center_offset=None,
    sphere_radius: float | None = None,
) -> trimesh.Trimesh:
    """cranium above the plane through the 3 registered landmarks: a sphere
    trim to kill far-away junk, an angled plane clip for stray rear/neck
    geometry a horizontal cut alone wouldn't catch, then the actual
    landmark-triangle plane as the real cranial boundary.

    the boundary is deliberately the raw landmark plane, not adjusted for
    the ears - the cranial region is defined by the landmarks, full stop.
    ear-avoidance belongs to the HC measurement itself, not the clip (see
    extract_measurements's landmarks param).

    the angled rear/neck plane and the landmark plane can both graze the
    surface at a shallow angle on an unusually-shaped head, leaving
    disconnected debris behind - keep_largest_component cleans that up
    here. a shallow graze can also leave a sawtooth along the boundary
    itself; that's remesh.clean_boundary's job, called here too, before
    any resampling - quadric decimation isn't boundary-aware, and running
    it on a still-jagged boundary can fragment the loop into pieces too
    small for _boundary_loops to even recognize as a loop afterward,
    which silently defeats any later boundary cleanup entirely. smoothing
    the boundary first means resample only ever simplifies an
    already-clean loop.

    trim_rear_neck exists because the rear/neck plane's numbers are
    hardcoded in the registered frame, tuned for a sellion-based
    registration. landmark_align only pins the 3 chosen landmarks to
    REFERENCE_TRIANGLE - it says nothing about where the rest of the head
    ends up, so registering on a different frontal point (subnasale) or
    skipping the center-of-mass nudge (com_translation=False) both tip the
    head into a different pose, and this plane can gouge straight into the
    occiput instead of cutting through the neck. pass False for any pass
    that isn't a plain sellion + com_translation=True registration - see
    pipeline.analyze_cranial and pipeline.analyze()."""
    center, radius = adjusted_trim_sphere(
        CRANIAL_TRIM_SPHERE_CENTER, CRANIAL_TRIM_SPHERE_RADIUS, sphere_center_offset, sphere_radius
    )
    mesh = clip_sphere(mesh, center=center, radius=radius, keep_inside=True)
    if trim_rear_neck:
        mesh = clip_plane(mesh, normal=CRANIAL_REAR_NECK_PLANE_NORMAL, origin=CRANIAL_REAR_NECK_PLANE_ORIGIN, invert=False)
    normal, origin = landmark_plane(landmarks)
    mesh = clip_plane(mesh, normal=normal, origin=origin, invert=False)
    mesh = keep_largest_component(mesh)
    return clean_boundary(mesh)


def facial_clip(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    sphere_center_offset=None,
    sphere_radius: float | None = None,
) -> trimesh.Trimesh:
    """just the face: a depth clip through the landmark-triangle centroid plus a
    sphere trim. landmarks = the mesh's own registered [sellion, left_tragus,
    right_tragus]. old facial_clip did the depth clip twice, ~1mm apart -
    collapsed that into one clip at the centroid depth.

    the sphere radius used to be a flat 115mm, tuned against a reference-sized
    face - fine on that one case but too tight for anyone with a larger face
    or head, silently slicing the chin off (clip_sphere isn't a real boolean
    cut, so a too-small radius just drops whole chin faces rather than
    trimming close). scaling the radius off this patient's own inter-tragus
    distance instead means it always clears their actual anatomy: checked
    against a synthetic face swept from 0.7x-1.8x a reference scale, 1.7x
    inter-tragus stayed >=10% above the true chin distance at every size,
    where the old fixed 115mm fell short even at reference scale.

    same keep_largest_component/clean_boundary cleanup as cranial_clip -
    two chained clips can graze a surface and fragment it on an unlucky
    head shape here too."""
    centroid = np.mean(landmarks, axis=0)
    inter_tragus = np.linalg.norm(landmarks[1] - landmarks[2])
    mesh = clip_plane(mesh, normal=FACIAL_DEPTH_PLANE_NORMAL, origin=[0, 20, centroid[2]], invert=False)
    center, radius = adjusted_trim_sphere(
        FACIAL_TRIM_SPHERE_CENTER, inter_tragus * FACIAL_TRIM_SPHERE_RADIUS_FACTOR, sphere_center_offset, sphere_radius
    )
    mesh = clip_sphere(mesh, center=center, radius=radius, keep_inside=True)
    mesh = keep_largest_component(mesh)
    return clean_boundary(mesh)


def preview_frame_offset(landmarks: np.ndarray, target: str, frame: str) -> np.ndarray:
    """the translation from `target`'s own registered frame into `frame`'s,
    for landmarks given in `frame`.

    the two registrations differ by exactly one translation and nothing
    else: registration.register() runs the same landmark_align for both
    targets and then, for target="face" only, shifts everything so the
    sellion sits at the origin (see its sellion_offset step). so in the
    cranial frame the landmark centroid is at the origin and the sellion is
    at S; in the facial frame everything is S lower. which means the
    facial clip's numbers - all written for a sellion-at-origin frame -
    land in completely the wrong place if they're read straight off cranial
    landmarks, and vice versa. that mismatch is what this corrects.

    note this is exact only for the pure landmark registration /align
    displays (no center-of-mass nudge, see the routers' _pure_align), which
    is the only frame the preview is ever drawn in."""
    if frame == target:
        return np.zeros(3)
    landmarks = np.asarray(landmarks, dtype=np.float64)
    # cranium -> face: drop the sellion onto the origin.
    # face -> cranium: put the landmark centroid back on the origin.
    return landmarks[0].copy() if target == "face" else landmarks.mean(axis=0)


def clip_preview_geometry(
    landmarks: np.ndarray,
    target: str,
    trim_rear_neck: bool = True,
    frame: str | None = None,
    sphere_center_offset=None,
    sphere_radius: float | None = None,
) -> dict:
    """the planes and spheres cranial_clip/facial_clip would cut this mesh
    with, as plain numbers - for drawing the clip in the viewer BEFORE the
    user commits to it (see the Per-patient workspace's align step).

    landmarks are the REGISTERED [sellion, left_tragus, right_tragus], the
    same ones the matching clip function takes, so everything here is already
    in the frame the viewer is showing - no transform needed on the way out.

    every element is reported, including the elements that rarely touch real
    anatomy (the 175mm cranial trim sphere, the rear/neck plane): the point is
    to show what the operation actually does, and the frontend decides how
    prominently to draw each one. `boundary` marks the plane that defines the
    region itself, which is the one worth drawing boldly - the others only
    strip stray scan junk.

    `frame` is which registration frame `landmarks` are expressed in, and
    defaults to `target` (i.e. they match). the Per-patient workspace draws
    both regions on one mesh, so one of the two is always being asked for
    in the OTHER target's frame - see preview_frame_offset, which is what
    makes that honest rather than merely plausible.

    sphere_center_offset / sphere_radius report the trim sphere the user
    has moved or resized, exactly as the matching clip call would cut with
    it (see adjusted_trim_sphere).

    deliberately derived from the same module constants the clip functions
    use, so the two cannot disagree."""
    landmarks = np.asarray(landmarks, dtype=np.float64)
    offset = preview_frame_offset(landmarks, target, frame if frame is not None else target)
    landmarks = landmarks - offset

    if target == "cranium":
        normal, origin = landmark_plane(landmarks)
        planes = [{"name": "landmark_plane", "normal": normal.tolist(), "origin": origin.tolist(), "boundary": True}]
        if trim_rear_neck:
            planes.append(
                {
                    "name": "rear_neck_plane",
                    "normal": list(CRANIAL_REAR_NECK_PLANE_NORMAL),
                    "origin": list(CRANIAL_REAR_NECK_PLANE_ORIGIN),
                    "boundary": False,
                }
            )
        center, radius = adjusted_trim_sphere(
            CRANIAL_TRIM_SPHERE_CENTER, CRANIAL_TRIM_SPHERE_RADIUS, sphere_center_offset, sphere_radius
        )
        spheres = [{"name": "trim_sphere", "center": center.tolist(), "radius": radius, "keep_inside": True}]
        return _shifted_into_frame({"target": target, "planes": planes, "spheres": spheres}, offset)

    centroid = np.mean(landmarks, axis=0)
    inter_tragus = float(np.linalg.norm(landmarks[1] - landmarks[2]))
    center, radius = adjusted_trim_sphere(
        FACIAL_TRIM_SPHERE_CENTER, inter_tragus * FACIAL_TRIM_SPHERE_RADIUS_FACTOR, sphere_center_offset, sphere_radius
    )
    return _shifted_into_frame(
        {
            "target": target,
            "planes": [
                {
                    "name": "depth_plane",
                    "normal": list(FACIAL_DEPTH_PLANE_NORMAL),
                    "origin": [0.0, 20.0, float(centroid[2])],
                    "boundary": True,
                }
            ],
            "spheres": [{"name": "trim_sphere", "center": center.tolist(), "radius": radius, "keep_inside": True}],
        },
        offset,
    )


def _shifted_into_frame(geometry: dict, offset: np.ndarray) -> dict:
    """moves a preview's origins/centres by `offset` - a pure translation,
    so plane normals and sphere radii are untouched."""
    if not offset.any():
        return geometry
    for plane in geometry["planes"]:
        plane["origin"] = (np.asarray(plane["origin"], dtype=np.float64) + offset).tolist()
    for sphere in geometry["spheres"]:
        sphere["center"] = (np.asarray(sphere["center"], dtype=np.float64) + offset).tolist()
    return geometry
