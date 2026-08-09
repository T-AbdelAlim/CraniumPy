"""tests for registration/rigid.py.

test_landmark_align_matches_legacy checks against the old picking.py math
(tests/fixtures/landmark_align_baseline.json). test_procrustes_icp_recovers_known_transform
is just a correctness check on made-up data.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from craniumpy_core.io import load_mesh
from craniumpy_core.registration.rigid import (
    REFERENCE_TRIANGLE,
    landmark_align,
    procrustes_icp,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "src" / "craniumpy_core" / "templates" / "clipped_template_xy.ply"


@pytest.fixture(scope="module")
def landmark_baseline() -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / "landmark_align_baseline.json"
    return json.loads(path.read_text())


def test_landmark_align_matches_legacy(landmark_baseline):
    landmarks = np.array(landmark_baseline["landmarks"])
    expected_translation = np.array(landmark_baseline["translation"])
    expected_final_points = np.array(landmark_baseline["final_points"])

    transform = landmark_align(landmarks, REFERENCE_TRIANGLE)

    np.testing.assert_allclose(transform.translation, transform.rotation @ expected_translation, atol=1e-6)
    result_points = transform.apply(landmarks)
    np.testing.assert_allclose(result_points, expected_final_points, atol=1e-6)


def test_landmark_align_centers_on_reference_centroid():
    # any reasonable landmark triple should end up with its centroid right
    # on top of the reference triangle's centroid
    landmarks = np.array([[5.0, -30.0, 60.0], [55.0, 5.0, -20.0], [-50.0, -10.0, -25.0]])
    transform = landmark_align(landmarks)
    result = transform.apply(landmarks)
    np.testing.assert_allclose(result.mean(axis=0), REFERENCE_TRIANGLE.mean(axis=0), atol=1e-8)


def test_procrustes_icp_recovers_known_transform():
    # point-to-point ICP is a local refinement method - given a decent
    # starting alignment it converges tight, but has no guarantee of finding
    # a big arbitrary rotation from a cold start. using a small perturbation
    # here since that's actually how this gets used (asymmetry's mirror
    # alignment starts already roughly lined up).
    rng = np.random.default_rng(1)
    mesh = load_mesh(TEMPLATE_PATH)
    source = np.asarray(mesh.vertices)[rng.choice(len(mesh.vertices), 500, replace=False)]

    true_R = _small_rotation(degrees=8.0)
    true_t = np.array([4.0, -3.0, 6.0])
    target = source @ true_R.T + true_t

    transform, _ = procrustes_icp(source, target)

    np.testing.assert_allclose(transform.rotation, true_R, atol=1e-4)
    np.testing.assert_allclose(transform.translation, true_t, atol=1e-3)


def _small_rotation(degrees: float) -> np.ndarray:
    """small rotation about a fixed arbitrary axis - meant to look like the
    kind of near-identity misalignment procrustes_icp actually deals with."""
    axis = np.array([0.3, 0.7, -0.6])
    axis = axis / np.linalg.norm(axis)
    angle = np.radians(degrees)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
