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

from craniumpy_core.clipping import clip_plane, clip_sphere, cranial_clip, facial_clip
from craniumpy_core.io import load_mesh
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_MESH_PATH = REPO_ROOT / "resources" / "test_mesh" / "test_mesh.ply"


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
    # is hardcoded in the registered frame, tuned against nasion-based
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

    dist = np.linalg.norm(clipped.vertices - np.array([0, 25, -25]), axis=1)
    assert dist.max() <= 115 + 1e-6
