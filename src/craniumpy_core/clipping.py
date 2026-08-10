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
    the ears - the cranial region this clips out is defined by the
    landmarks themselves, full stop. (an earlier version of this function
    raised the boundary to clear the ears, on the theory that it was the
    same root cause as the HC slice landing on the ears - it isn't the fix
    that was actually wanted: the clip stays at the landmarks, only the HC
    measurement itself should skip past ear-level slices, see
    extract_measurements's landmarks param.)

    that angled rear/neck plane is the risky one - found on a real template
    that it can graze the actual cranium surface at a shallow angle instead
    of passing cleanly through the neck, for a head shaped differently than
    whatever this was tuned against. slicing at a near-tangent angle leaves
    a scatter of tiny disconnected slivers behind (1 component going in,
    225 by the time all three cuts here had run, on that file). dropping
    everything but the largest component at the end cleans that up - it's
    debris, not a hole, so this doesn't touch the intentional open boundary
    the landmark-plane cut leaves (see the module docstring: clips are left
    open on purpose, repair closes them later).

    the landmark-plane cut itself can graze at a shallow angle too, same
    root cause as the rear/neck one above but along the actual cranial
    boundary this time instead of debris headed for the trash. worse,
    found on a real scan that it's often not just one grazing spot but the
    plane running close to tangent for its *whole* length, leaving a
    sawtooth around the entire rim - clean_boundary handles that (see its
    docstring in remesh.py for why this needs more than just dropping bad
    triangles).

    trim_rear_neck exists because that angled plane's numbers - [0, 0.6, 1]
    normal, [0, -60, -50] origin - are hardcoded in the REGISTERED frame,
    tuned against a nasion-based registration. landmark_align only pins the
    3 chosen landmarks to REFERENCE_TRIANGLE - it says nothing about where
    the rest of the head ends up, and subnasale sits far enough below (and
    forward of) nasion that forcing IT onto the same reference triangle
    tips the whole head into a different pose, dragging the actual back of
    the skull to a different spot in this same fixed coordinate frame.
    found on a real scan (pipeline.analyze_cranial's alt-frontal pass,
    registered via subnasale): this same plane, which cuts cleanly through
    the neck in the nasion frame, gouges straight into the occiput in the
    subnasale frame - not debris this time, a genuine notch carved out of
    the kept cranium, big enough that keep_largest_component and
    clean_boundary can't paper over it since the surface never actually
    disconnects, just dents inward by ~30mm. pass False for any pass that
    didn't register on nasion - see pipeline.analyze_cranial.

    turns out registering on nasion isn't even enough on its own - the
    same failure mode shows up with com_translation=False too. register()'s
    CoM Z-nudge isn't just cosmetic "smooth out imprecise clicking" the way
    it reads at a glance: on a real scan, turning it off left the head
    sitting a genuine 25mm further back than the pose this plane (and the
    sphere trim above it) were tuned against, which was enough for BOTH to
    start cutting into real cranium instead of the neck/background junk
    they're meant for - the sphere trim's old radius (125) actually clipped
    real occiput too, not just the angled plane. bumped that radius to 175
    for exactly this reason, but the angled plane still isn't safe at that
    pose, so pass trim_rear_neck=False there as well - pipeline.analyze()
    and analyze_cranial() both do this by tying trim_rear_neck to whatever
    com_translation actually was, not just to which landmark drove
    registration."""
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

    same keep_largest_component cleanup as cranial_clip, for the same
    reason - two chained clips (a plane then a sphere) is the same kind of
    setup that can graze a surface and fragment it on an unlucky head
    shape, even though the specific bug that surfaced this was found via
    cranial_clip."""
    centroid = np.mean(landmarks, axis=0)
    mesh = clip_plane(mesh, normal=[0, 0, 1], origin=[0, 20, centroid[2]], invert=False)
    mesh = clip_sphere(mesh, center=(0, 25, -25), radius=115, keep_inside=True)
    mesh = keep_largest_component(mesh)
    return clean_boundary(mesh)
