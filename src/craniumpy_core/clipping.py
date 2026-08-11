"""cutting the mesh down to just the cranium or just the face.

ported the geometry from gui_methods.py's cranial_cut/facial_clip (old repo),
swapping pyvista's .clip()/.clip_surface() for trimesh's slice_mesh_plane.
works on an already-registered mesh (see registration.rigid.landmark_align) -
the plane/sphere numbers below are in that registered frame, same numbers
the old app used, except the cranial boundary itself: the old app cut at a
hardcoded y=-21 regardless of where the landmarks actually landed, which in
practice cut well below the nasion-tragus plane. cranial_clip now cuts
through the actual registered landmark plane instead - see _landmark_plane.

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


def _landmark_plane(landmarks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """normal + origin of the plane through the 3 registered landmarks
    (nasion, left_tragus, right_tragus), oriented so +normal points toward
    the top of the head - flips the cross product if it doesn't, since
    landmark order alone doesn't guarantee a consistent winding."""
    landmarks = np.asarray(landmarks, dtype=np.float64)
    origin = landmarks.mean(axis=0)
    normal = np.cross(landmarks[1] - landmarks[0], landmarks[2] - landmarks[0])
    normal = normal / np.linalg.norm(normal)
    if normal[1] < 0:
        normal = -normal
    return normal, origin


def cranial_clip(mesh: trimesh.Trimesh, landmarks: np.ndarray, trim_rear_neck: bool = True) -> trimesh.Trimesh:
    """cranium above the plane through the 3 registered landmarks: a sphere
    trim to kill far-away junk, an angled plane clip for stray rear/neck
    geometry a horizontal cut alone wouldn't catch, then the actual
    landmark-triangle plane as the real cranial boundary.

    the boundary is deliberately the raw landmark plane, not adjusted for
    the ears - the cranial region is defined by the landmarks, full stop.
    ear-avoidance belongs to the HC measurement itself, not the clip (see
    extract_measurements's landmarks param).

    the angled rear/neck plane and the landmark plane can both graze the
    surface at a shallow angle on an unusually-shaped head, leaving either
    disconnected debris (keep_largest_component cleans that up) or a
    sawtooth along the boundary itself (clean_boundary handles that, see
    remesh.py).

    trim_rear_neck exists because the rear/neck plane's numbers are
    hardcoded in the registered frame, tuned for a nasion-based
    registration. landmark_align only pins the 3 chosen landmarks to
    REFERENCE_TRIANGLE - it says nothing about where the rest of the head
    ends up, so registering on a different frontal point (subnasale) or
    skipping the center-of-mass nudge (com_translation=False) both tip the
    head into a different pose, and this plane can gouge straight into the
    occiput instead of cutting through the neck. pass False for any pass
    that isn't a plain nasion + com_translation=True registration - see
    pipeline.analyze_cranial and pipeline.analyze()."""
    mesh = clip_sphere(mesh, center=(0, 40, 0), radius=175, keep_inside=True)
    if trim_rear_neck:
        mesh = clip_plane(mesh, normal=[0, 0.6, 1], origin=[0, -60, -50], invert=False)
    normal, origin = _landmark_plane(landmarks)
    mesh = clip_plane(mesh, normal=normal, origin=origin, invert=False)
    mesh = keep_largest_component(mesh)
    return clean_boundary(mesh)


def facial_clip(mesh: trimesh.Trimesh, landmarks: np.ndarray) -> trimesh.Trimesh:
    """just the face: a depth clip through the landmark-triangle centroid plus a
    sphere trim. landmarks = the mesh's own registered [nasion, left_tragus,
    right_tragus]. old facial_clip did the depth clip twice, ~1mm apart -
    collapsed that into one clip at the centroid depth.

    same keep_largest_component/clean_boundary cleanup as cranial_clip -
    two chained clips can graze a surface and fragment it on an unlucky
    head shape here too."""
    centroid = np.mean(landmarks, axis=0)
    mesh = clip_plane(mesh, normal=[0, 0, 1], origin=[0, 20, centroid[2]], invert=False)
    mesh = clip_sphere(mesh, center=(0, 25, -25), radius=115, keep_inside=True)
    mesh = keep_largest_component(mesh)
    return clean_boundary(mesh)
