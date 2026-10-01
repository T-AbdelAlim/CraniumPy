"""tests for clipping.py.

test_clip_plane_keeps_positive_normal_side and test_clip_sphere_keeps_inside
pin down the sign conventions - checked these against real pyvista behavior
first, getting this backwards would silently cut away the wrong half of a
head and you'd never notice from the code alone. the cranial_clip/facial_clip
tests are just smoke tests on the raw unregistered test mesh - not checking
anatomical correctness (needs a registered mesh for that, later pipeline
stage), just that the output actually respects the constraints each clip is
supposed to enforce.
"""

import numpy as np
import pytest
import trimesh

from craniumpy_core import clipping
from craniumpy_core.clipping import clip_plane, clip_sphere, cranial_clip, facial_clip
from craniumpy_core.io import load_mesh
from craniumpy_core.pipeline import register
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_MESH_PATH = REPO_ROOT / "tests" / "fixtures" / "test_mesh.ply"


def test_clip_plane_keeps_positive_normal_side():
    sphere = trimesh.creation.icosphere(radius=10)
    clipped = clip_plane(sphere, normal=[0, 1, 0], origin=[0, 0, 0])
    assert clipped.vertices[:, 1].min() >= -1e-8
    assert clipped.vertices[:, 1].max() > 5


def test_clip_plane_invert_keeps_negative_normal_side():
    sphere = trimesh.creation.icosphere(radius=10)
    clipped = clip_plane(sphere, normal=[0, 1, 0], origin=[0, 0, 0], invert=True)
    assert clipped.vertices[:, 1].max() <= 1e-8
    assert clipped.vertices[:, 1].min() < -5


def test_clip_sphere_keeps_inside():
    # Off-center clip sphere against a bigger icosphere, so part of the
    # icosphere's surface genuinely falls inside the clip radius and part
    # doesn't (a mesh and clip sphere concentric at the same center would
    # never split -- every vertex would be uniformly in or out).
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=20)
    clipped = clip_sphere(mesh, center=(15, 0, 0), radius=8, keep_inside=True)
    dist = np.linalg.norm(clipped.vertices - np.array([15, 0, 0]), axis=1)
    assert dist.max() <= 8 + 1e-6
    assert 0 < len(clipped.vertices) < len(mesh.vertices)


def test_clip_sphere_keeps_outside():
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=20)
    clipped = clip_sphere(mesh, center=(15, 0, 0), radius=8, keep_inside=False)
    dist = np.linalg.norm(clipped.vertices - np.array([15, 0, 0]), axis=1)
    assert dist.min() >= 8 - 1e-6
    assert 0 < len(clipped.vertices) < len(mesh.vertices)


@pytest.fixture(scope="module")
def test_mesh() -> trimesh.Trimesh:
    return load_mesh(TEST_MESH_PATH)


def test_cranial_clip_respects_all_three_constraints(test_mesh):
    # not a registered mesh, so these landmarks are just a plausible-looking
    # triangle on it (same ones test_pipeline.py's real-mesh test uses) -
    # good enough to check the clip actually cuts through the plane they
    # define, which is the constraint that matters now (see clipping.py).
    landmarks = np.array([[0.0, -30.0, 90.0], [55.0, -30.0, 0.0], [-55.0, -30.0, 0.0]])
    clipped = cranial_clip(test_mesh, landmarks)
    assert len(clipped.vertices) > 0
    assert len(clipped.vertices) < len(test_mesh.vertices)

    dist = np.linalg.norm(clipped.vertices - np.array([0, 40, 0]), axis=1)
    assert dist.max() <= 175 + 1e-6

    plane_signed_diag = (clipped.vertices - np.array([0, -60, -50])) @ np.array([0, 0.6, 1])
    assert plane_signed_diag.min() >= -1e-6

    origin = landmarks.mean(axis=0)
    normal = np.cross(landmarks[1] - landmarks[0], landmarks[2] - landmarks[0])
    normal = normal / np.linalg.norm(normal)
    if normal[1] < 0:
        normal = -normal
    plane_signed = (clipped.vertices - origin) @ normal
    assert plane_signed.min() >= -1e-6


def test_cranial_clip_trim_rear_neck_false_skips_that_plane(test_mesh):
    # regression test for the alt-frontal-landmark bug: the rear/neck plane
    # is hardcoded in the registered frame, tuned against sellion-based
    # registration - registering on a different frontal landmark (e.g.
    # subnasale) tips the whole head into a different pose in that same
    # fixed frame, and on a real scan this plane ended up gouging into the
    # actual occiput instead of the neck. trim_rear_neck=False (used by
    # pipeline.analyze_cranial's alt-frontal pass) skips that plane
    # entirely - just confirming here that the constraint it would enforce
    # is in fact no longer enforced, i.e. the flag actually does something.
    landmarks = np.array([[0.0, -30.0, 90.0], [55.0, -30.0, 0.0], [-55.0, -30.0, 0.0]])
    clipped = cranial_clip(test_mesh, landmarks, trim_rear_neck=False)
    assert len(clipped.vertices) > 0

    plane_signed_diag = (clipped.vertices - np.array([0, -60, -50])) @ np.array([0, 0.6, 1])
    assert plane_signed_diag.min() < -1e-6

    # the landmark-plane boundary (the one that actually matters) still holds
    origin = landmarks.mean(axis=0)
    normal = np.cross(landmarks[1] - landmarks[0], landmarks[2] - landmarks[0])
    normal = normal / np.linalg.norm(normal)
    if normal[1] < 0:
        normal = -normal
    plane_signed = (clipped.vertices - origin) @ normal
    assert plane_signed.min() >= -1e-6


def test_facial_clip_respects_both_constraints(test_mesh):
    landmarks = np.array([[0.0, 0.0, 60.0], [60.0, 0.0, -20.0], [-60.0, 0.0, -20.0]])
    clipped = facial_clip(test_mesh, landmarks)
    assert len(clipped.vertices) > 0
    assert len(clipped.vertices) < len(test_mesh.vertices)

    centroid_z = landmarks.mean(axis=0)[2]
    assert clipped.vertices[:, 2].min() >= centroid_z - 1e-6

    inter_tragus = np.linalg.norm(landmarks[1] - landmarks[2])
    dist = np.linalg.norm(clipped.vertices - np.array([0, 25, -25]), axis=1)
    assert dist.max() <= inter_tragus * 1.7 + 1e-6


def _face_ellipsoid(scale: float) -> tuple[trimesh.Trimesh, np.ndarray]:
    """head-scale ellipsoid with a REFERENCE_TRIANGLE-proportioned landmark
    triangle (same trick as test_pipeline.py's _ellipsoid_with_landmarks) so
    landmark_align has a sane rigid transform to solve at every scale,
    instead of contorting the mesh into a weird pose to match a landmark
    triangle shaped nothing like a real face - lets scale alone stand in for
    "how big is this patient's face" so a clip that only works at one scale
    shows up immediately."""
    mesh = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    v = np.asarray(mesh.vertices).copy()
    front = v[:, 2] > 0
    v[front, 2] *= 1.3
    offset = np.array([0.0, -10.0, 10.0])
    mesh.vertices = (v * np.array([70.0, 90.0, 65.0]) + offset) * scale
    landmarks = (REFERENCE_TRIANGLE + offset) * scale
    return mesh, landmarks


@pytest.mark.parametrize("scale", [0.7, 1.0, 1.5, 1.8, 2.2])
def test_facial_clip_keeps_chin_at_any_face_size(scale):
    # regression test: the sphere trim's radius used to be a flat 115mm,
    # tuned against one reference-sized face - too tight for anyone bigger
    # (or even a plain-average face, it turned out), silently slicing the
    # chin off since clip_sphere drops whole faces rather than trimming
    # close. radius now scales off this patient's own inter-tragus
    # distance (see clipping.facial_clip), so the true chin should survive
    # across a wide range of face sizes, not just the one it was tuned on.
    mesh, landmarks = _face_ellipsoid(scale)
    reg = register(mesh, landmarks, target="face", com_translation=True)
    original_chin_y = reg.mesh.vertices[:, 1].min()

    clipped = facial_clip(reg.mesh, reg.landmarks)

    clipped_chin_y = clipped.vertices[:, 1].min()
    assert clipped_chin_y == pytest.approx(original_chin_y, abs=2.0)


# the preview's whole value is that it describes the cut that will actually
# happen. these assert it against the module constants the clip functions
# themselves read, so moving a plane in one place without the other breaks
# the build instead of silently showing the user a lie.
def test_cranial_preview_matches_the_constants_the_clip_uses():
    landmarks = REFERENCE_TRIANGLE.copy()

    geometry = clipping.clip_preview_geometry(landmarks, "cranium")

    assert geometry["target"] == "cranium"
    by_name = {p["name"]: p for p in geometry["planes"]}
    # the landmark plane is the region's real edge - the one to draw boldly
    assert by_name["landmark_plane"]["boundary"] is True
    normal, origin = clipping.landmark_plane(landmarks)
    assert by_name["landmark_plane"]["normal"] == pytest.approx(normal.tolist())
    assert by_name["landmark_plane"]["origin"] == pytest.approx(origin.tolist())
    assert by_name["rear_neck_plane"]["normal"] == pytest.approx(list(clipping.CRANIAL_REAR_NECK_PLANE_NORMAL))
    assert by_name["rear_neck_plane"]["origin"] == pytest.approx(list(clipping.CRANIAL_REAR_NECK_PLANE_ORIGIN))
    assert by_name["rear_neck_plane"]["boundary"] is False
    (sphere,) = geometry["spheres"]
    assert sphere["center"] == pytest.approx(list(clipping.CRANIAL_TRIM_SPHERE_CENTER))
    assert sphere["radius"] == pytest.approx(clipping.CRANIAL_TRIM_SPHERE_RADIUS)
    assert sphere["keep_inside"] is True


def test_cranial_preview_drops_the_rear_neck_plane_when_the_clip_would():
    geometry = clipping.clip_preview_geometry(REFERENCE_TRIANGLE.copy(), "cranium", trim_rear_neck=False)

    assert [p["name"] for p in geometry["planes"]] == ["landmark_plane"]


def test_facial_preview_scales_its_sphere_off_this_patients_face():
    # same inter-tragus scaling facial_clip does - a preview drawn at the
    # fixed reference size would be wrong for every other face.
    landmarks = REFERENCE_TRIANGLE * 1.5

    geometry = clipping.clip_preview_geometry(landmarks, "face")

    (plane,) = geometry["planes"]
    assert plane["name"] == "depth_plane"
    assert plane["boundary"] is True
    assert plane["normal"] == pytest.approx(list(clipping.FACIAL_DEPTH_PLANE_NORMAL))
    assert plane["origin"] == pytest.approx([0.0, 20.0, float(np.mean(landmarks, axis=0)[2])])
    (sphere,) = geometry["spheres"]
    inter_tragus = float(np.linalg.norm(landmarks[1] - landmarks[2]))
    assert sphere["center"] == pytest.approx(list(clipping.FACIAL_TRIM_SPHERE_CENTER))
    assert sphere["radius"] == pytest.approx(inter_tragus * clipping.FACIAL_TRIM_SPHERE_RADIUS_FACTOR)


def test_preview_of_the_other_target_lands_where_that_target_would_clip():
    # the Per-patient workspace draws both regions on ONE registered mesh,
    # so one of them is always asked for in the other's frame. the two
    # registrations differ by the sellion shift register() applies for
    # facial targets, and reading the facial numbers straight off cranial
    # landmarks put the facial plane tens of millimetres out - it looked
    # plausible and was wrong, which is the worst thing a preview can be.
    mesh = load_mesh(TEST_MESH_PATH)
    picks = np.array([[10.0, 5.0, 120.0], [-45.0, 30.0, 40.0], [70.0, 20.0, 35.0]])
    cranial = register(mesh, picks, target="cranium", com_translation=False)
    facial = register(mesh, picks, target="face", com_translation=False)
    # the frames differ by exactly this, and by nothing else
    shift = cranial.landmarks[0]

    drawn_on_cranial_mesh = clipping.clip_preview_geometry(cranial.landmarks, "face", frame="cranium")
    truth = clipping.clip_preview_geometry(facial.landmarks, "face")

    assert drawn_on_cranial_mesh["planes"][0]["origin"] == pytest.approx(
        (np.asarray(truth["planes"][0]["origin"]) + shift).tolist(), abs=1e-6
    )
    assert drawn_on_cranial_mesh["spheres"][0]["center"] == pytest.approx(
        (np.asarray(truth["spheres"][0]["center"]) + shift).tolist(), abs=1e-6
    )
    assert drawn_on_cranial_mesh["spheres"][0]["radius"] == pytest.approx(truth["spheres"][0]["radius"])


def test_preview_of_the_cranial_region_on_a_facial_mesh_lands_right_too():
    mesh = load_mesh(TEST_MESH_PATH)
    picks = np.array([[10.0, 5.0, 120.0], [-45.0, 30.0, 40.0], [70.0, 20.0, 35.0]])
    cranial = register(mesh, picks, target="cranium", com_translation=False)
    facial = register(mesh, picks, target="face", com_translation=False)
    shift = cranial.landmarks[0]

    drawn_on_facial_mesh = clipping.clip_preview_geometry(facial.landmarks, "cranium", frame="face")
    truth = clipping.clip_preview_geometry(cranial.landmarks, "cranium")

    for drawn, expected in zip(drawn_on_facial_mesh["planes"], truth["planes"]):
        assert drawn["name"] == expected["name"]
        assert drawn["origin"] == pytest.approx((np.asarray(expected["origin"]) - shift).tolist(), abs=1e-6)
        assert drawn["normal"] == pytest.approx(expected["normal"], abs=1e-6)
    assert drawn_on_facial_mesh["spheres"][0]["center"] == pytest.approx(
        (np.asarray(truth["spheres"][0]["center"]) - shift).tolist(), abs=1e-6
    )


def test_preview_in_its_own_frame_is_left_alone():
    landmarks = REFERENCE_TRIANGLE.copy()

    assert clipping.clip_preview_geometry(landmarks, "cranium", frame="cranium") == clipping.clip_preview_geometry(
        landmarks, "cranium"
    )


def test_adjusting_the_trim_sphere_moves_the_cut_and_the_preview_together():
    # the preview's promise is that the sphere drawn is the sphere that
    # cuts - so the adjustment has to reach both through the same code.
    mesh = load_mesh(TEST_MESH_PATH)
    landmarks = REFERENCE_TRIANGLE.copy()
    offset = [0.0, -10.0, 25.0]

    preview = clipping.clip_preview_geometry(landmarks, "cranium", sphere_center_offset=offset, sphere_radius=90.0)

    (sphere,) = preview["spheres"]
    assert sphere["center"] == pytest.approx(
        (np.asarray(clipping.CRANIAL_TRIM_SPHERE_CENTER) + np.asarray(offset)).tolist()
    )
    assert sphere["radius"] == pytest.approx(90.0)
    # and the real clip keeps less of the mesh at that much smaller radius
    wide = clipping.cranial_clip(mesh, landmarks)
    tight = clipping.cranial_clip(mesh, landmarks, sphere_center_offset=offset, sphere_radius=90.0)
    assert len(tight.vertices) < len(wide.vertices)


def test_untouched_sphere_arguments_change_nothing():
    assert clipping.adjusted_trim_sphere((1.0, 2.0, 3.0), 175.0) == (
        pytest.approx(np.array([1.0, 2.0, 3.0])),
        175.0,
    )


def test_the_cut_follows_the_sphere_wherever_it_is_moved():
    # "tighter sphere keeps less" would still pass if the offset were
    # silently dropped and only the radius honoured. this pins the centre
    # too: pushing the sphere along +x has to take the cut with it, leaving
    # a mesh that reaches further right and less far left than the default.
    mesh = load_mesh(TEST_MESH_PATH)
    landmarks = REFERENCE_TRIANGLE.copy()

    centred = clipping.cranial_clip(mesh, landmarks, sphere_radius=110.0)
    moved = clipping.cranial_clip(mesh, landmarks, sphere_center_offset=[40.0, 0.0, 0.0], sphere_radius=110.0)

    assert moved.vertices[:, 0].min() > centred.vertices[:, 0].min()
    assert moved.vertices[:, 0].max() >= centred.vertices[:, 0].max()


def test_a_sphere_bigger_than_the_head_takes_nothing_off():
    # worth pinning because it's the thing that looks like a bug from the
    # outside: the tuned cranial default is 175mm, far larger than any
    # head, so moving the slider a little changes nothing visible at all.
    mesh = load_mesh(TEST_MESH_PATH)
    landmarks = REFERENCE_TRIANGLE.copy()

    default = clipping.cranial_clip(mesh, landmarks)
    roomy = clipping.cranial_clip(mesh, landmarks, sphere_radius=250.0)

    assert len(roomy.vertices) == len(default.vertices)
