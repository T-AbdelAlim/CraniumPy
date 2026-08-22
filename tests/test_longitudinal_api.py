"""tests for api/routers/longitudinal.py's LongitudinalMeshRef.template
support - the "distance heatmap" overlay's custom-reference mode (see the
Longitudinal workspace's 3D Morphing tab) needs to diff an arbitrary
NICP-fit session against a bare shipped template, not just another
session. self-contained rather than importing test_api.py's own helpers -
they're a handful of lines each, not worth a cross-test-module import."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.main import app
from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "src" / "craniumpy_core" / "templates"
TEMPLATE_PATH = TEMPLATES_DIR / "template_xy_com.ply"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def landmarks_payload() -> list[dict]:
    return [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in REFERENCE_TRIANGLE]


def _poll_status(client: TestClient, session_id: str, timeout: float) -> str:
    deadline = time.time() + timeout
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.2)
    return status


def _fit_session_to_template(client: TestClient, landmarks_payload: list[dict], template_name: str = "clipped_template_xy") -> str:
    with open(TEMPLATE_PATH, "rb") as f:
        response = client.post("/api/sessions", files=[("files", ("template_xy_com.ply", f, "application/octet-stream"))])
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]

    response = client.post(f"/api/sessions/{session_id}/clip", json={"target": "cranium", "landmarks": landmarks_payload})
    assert response.status_code == 200, response.text
    assert _poll_status(client, session_id, 60) == "done"

    # small alpha schedule / relaxed threshold - fast is all this test
    # needs, real tuning is exercised in test_nicp.py.
    response = client.post(
        f"/api/sessions/{session_id}/run",
        json={"nicp": {"template": template_name, "alpha_start": 50, "alpha_end": 1, "alpha_steps": 3, "inner_iters": 1, "dist_threshold": 50.0}},
    )
    assert response.status_code == 200, response.text
    assert _poll_status(client, session_id, 60) == "done"
    return session_id


def test_diff_against_a_shipped_template_ref(client, landmarks_payload):
    session_id = _fit_session_to_template(client, landmarks_payload, "clipped_template_xy")

    response = client.post(
        "/api/longitudinal/diff",
        json={
            "mesh_a": {"template": "clipped_template_xy"},
            "mesh_b": {"session_id": session_id, "stage": "nicp_result"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    template = trimesh.load(TEMPLATES_DIR / "clipped_template_xy.ply", process=False, force="mesh")
    assert body["vertex_count"] == len(template.vertices)
    assert len(body["heatmap"]) == len(template.vertices)


def test_diff_unknown_template_name_is_a_clear_error(client, landmarks_payload):
    session_id = _fit_session_to_template(client, landmarks_payload, "clipped_template_xy")

    response = client.post(
        "/api/longitudinal/diff",
        json={
            "mesh_a": {"template": "not-a-real-template"},
            "mesh_b": {"session_id": session_id, "stage": "nicp_result"},
        },
    )

    assert response.status_code == 404


def test_diff_template_vertex_mismatch_is_a_clear_error(client, landmarks_payload):
    # fit to one template, then diff against a DIFFERENT (different vertex
    # count) template - not actually correspondent, must not silently
    # produce a meaningless heatmap.
    session_id = _fit_session_to_template(client, landmarks_payload, "clipped_template_xy")

    response = client.post(
        "/api/longitudinal/diff",
        json={
            "mesh_a": {"template": "template_face"},
            "mesh_b": {"session_id": session_id, "stage": "nicp_result"},
        },
    )

    assert response.status_code == 400
