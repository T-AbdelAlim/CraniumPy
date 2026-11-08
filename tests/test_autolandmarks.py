"""automated landmarking: finds the template's own landmarks back, whatever
the orientation and position of the mesh, and the API hands them out in
the uploaded mesh's own coordinates."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from craniumpy_core import autolandmarks
from craniumpy_core.io import load_mesh
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE
from craniumpy_core.template_registry import TEMPLATES_DIR

NAMES = ("sellion", "left_tragus", "right_tragus")


@pytest.fixture(scope="module")
def template():
    return load_mesh(TEMPLATES_DIR / "template_xy.ply")


def _moved(mesh, seed):
    R = Rotation.random(random_state=seed).as_matrix()
    t = np.array([150.0, -60.0, 400.0])
    out = mesh.copy()
    out.vertices = np.asarray(mesh.vertices) @ R.T + t
    return out, R, t


def test_head_frame_of_the_reference_triangle_is_the_identity():
    frame = autolandmarks._landmark_frame(*REFERENCE_TRIANGLE, scale=1.0)
    assert np.allclose(frame.to_head(REFERENCE_TRIANGLE), REFERENCE_TRIANGLE, atol=1e-6)


@pytest.mark.parametrize("seed", [3, 11])
def test_template_landmarks_are_found_in_any_orientation(template, seed):
    mesh, R, t = _moved(template, seed)
    found = autolandmarks.detect_landmarks(mesh)
    for i, name in enumerate(NAMES):
        back = (getattr(found, name) - t) @ R
        assert np.linalg.norm(back - REFERENCE_TRIANGLE[i]) < 5.0, name
    # subnasale: on the midline, below the sellion and in front of the tragi
    sub = (found.subnasale - t) @ R
    assert abs(sub[0]) < 5.0
    assert -50.0 < sub[1] < -20.0
    assert sub[2] > 30.0
    assert not found.flags


def test_points_lie_on_the_mesh(template):
    found = autolandmarks.detect_landmarks(template)
    vertices = np.asarray(template.vertices)
    for name in (*NAMES, "subnasale"):
        assert np.min(np.linalg.norm(vertices - getattr(found, name), axis=1)) < 1e-6


def test_api_returns_points_in_the_uploaded_frame():
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    with open(TEMPLATES_DIR / "template_xy.ply", "rb") as f:
        response = client.post("/api/sessions", files=[("files", ("template_xy.ply", f, "application/octet-stream"))])
    session_id = response.json()["session_id"]
    response = client.post(f"/api/sessions/{session_id}/auto-landmarks")
    assert response.status_code == 200, response.text
    body = response.json()
    for i, name in enumerate(NAMES):
        p = body[name]
        assert np.linalg.norm(np.array([p["x"], p["y"], p["z"]]) - REFERENCE_TRIANGLE[i]) < 5.0
    assert set(body) >= {"subnasale", "scores", "flags"}


def test_api_unknown_session_is_404():
    from fastapi.testclient import TestClient

    from api.main import app

    assert TestClient(app).post("/api/sessions/nope/auto-landmarks").status_code == 404
