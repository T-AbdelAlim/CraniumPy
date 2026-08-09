"""API tests - upload -> analyze -> poll status -> results -> mesh export
-> results bundle.

landmarks are always manual now (see pipeline.py). using REFERENCE_TRIANGLE
as landmarks on template_xy_com.ply since it's already in the frame the
clip constants assume, so harmonize() has something real to work with
without needing an actual scan.
"""

import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.main import app
from craniumpy_core.io import load_mesh
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


def _upload(client: TestClient) -> str:
    with open(TEMPLATE_PATH, "rb") as f:
        response = client.post(
            "/api/sessions", files=[("files", ("template_xy_com.ply", f, "application/octet-stream"))]
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _run_analysis(client: TestClient, session_id: str, body: dict, timeout: float = 30) -> str:
    response = client.post(f"/api/sessions/{session_id}/analyze", json=body)
    assert response.status_code == 200, response.text

    deadline = time.time() + timeout
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.2)
    return status


def test_upload_returns_session_and_vertex_count(client):
    session_id = _upload(client)
    assert session_id

    response = client.get(f"/api/sessions/{session_id}/mesh/original")
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert len(response.content) > 0


def test_upload_rejects_unsupported_extension(client):
    response = client.post(
        "/api/sessions", files=[("files", ("mesh.xyz", b"not a mesh", "application/octet-stream"))]
    )
    assert response.status_code == 400


def test_unknown_session_returns_404(client):
    response = client.get("/api/sessions/does-not-exist/status")
    assert response.status_code == 404


def test_list_templates(client):
    response = client.get("/api/templates")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert "template_xy" in names
    assert len(response.json()) >= 1


def test_get_template_mesh(client):
    response = client.get("/api/templates/template_xy_com/mesh")
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert len(response.content) > 0


def test_get_unknown_template_mesh_404s(client):
    response = client.get("/api/templates/not-a-real-template/mesh")
    assert response.status_code == 404


def _glb_min_y(content: bytes) -> float:
    mesh = trimesh.load(BytesIO(content), file_type="glb", process=False, force="mesh")
    return float(mesh.vertices[:, 1].min())


def test_get_template_mesh_clip_cranial_cuts_near_landmark_plane(client):
    # regression test for the overlay comparing against a stale pre-baked
    # clipped_template_*.ply - the live clip=cranial pass has to land at the
    # actual landmark plane, not wherever that file happened to be cut.
    unclipped = client.get("/api/templates/template_xy_com/mesh")
    clipped = client.get("/api/templates/template_xy_com/mesh?clip=cranial")
    assert clipped.status_code == 200
    assert _glb_min_y(unclipped.content) < -50
    assert abs(_glb_min_y(clipped.content)) < 10


def test_get_template_mesh_invalid_clip_400s(client):
    response = client.get("/api/templates/template_xy_com/mesh?clip=nonsense")
    assert response.status_code == 400


def test_get_custom_template_mesh_from_path(client):
    response = client.get(f"/api/templates/custom/mesh?path={TEMPLATE_PATH}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert len(response.content) > 0


def test_get_custom_template_mesh_missing_path_400s(client):
    response = client.get("/api/templates/custom/mesh?path=C:/nope/not-a-real-file.ply")
    assert response.status_code == 400


def test_upload_custom_template_mesh(client):
    with open(TEMPLATE_PATH, "rb") as f:
        response = client.post(
            "/api/templates/custom/upload",
            files=[("files", ("custom_template.ply", f, "application/octet-stream"))],
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert len(response.content) > 0


def test_upload_custom_template_mesh_with_clip(client):
    with open(TEMPLATE_PATH, "rb") as f:
        response = client.post(
            "/api/templates/custom/upload?clip=cranial",
            files=[("files", ("custom_template.ply", f, "application/octet-stream"))],
        )
    assert response.status_code == 200
    assert abs(_glb_min_y(response.content)) < 10


def test_get_custom_template_mesh_with_clip(client):
    response = client.get(f"/api/templates/custom/mesh?path={TEMPLATE_PATH}&clip=cranial")
    assert response.status_code == 200
    assert abs(_glb_min_y(response.content)) < 10


def test_full_analysis_flow_rigid(client, landmarks_payload):
    session_id = _upload(client)
    status = _run_analysis(
        client,
        session_id,
        {"target": "cranium", "landmarks": landmarks_payload, "com_translation": True},
    )
    assert status == "done"

    results = client.get(f"/api/sessions/{session_id}/results")
    assert results.status_code == 200, results.text
    body = results.json()
    assert len(body["landmarks"]) == 3
    assert body["craniometrics"] is not None
    assert body["craniometrics"]["depth_mm"] > 0
    assert len(body["craniometrics"]["hc_slice_polygon"]) > 3
    assert body["vertex_count"] > 0

    mesh_response = client.get(f"/api/sessions/{session_id}/mesh/result")
    assert mesh_response.status_code == 200
    assert len(mesh_response.content) > 0

    registered_response = client.get(f"/api/sessions/{session_id}/mesh/registered")
    assert registered_response.status_code == 200
    assert len(registered_response.content) > 0


def test_analyze_progress_is_reported(client, landmarks_payload):
    session_id = _upload(client)
    client.post(
        f"/api/sessions/{session_id}/analyze",
        json={"target": "cranium", "landmarks": landmarks_payload},
    )
    # at least one poll should show a real stage, not just idle - proves
    # progress is actually wired through and not just a static "running" flag
    seen_stages = set()
    deadline = time.time() + 30
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status").json()
        if status["progress"]:
            seen_stages.add(status["progress"]["stage"])
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert seen_stages - {"idle"}


def test_manual_clip_mode(client, landmarks_payload):
    session_id = _upload(client)
    status = _run_analysis(
        client,
        session_id,
        {
            "target": "cranium",
            "landmarks": landmarks_payload,
            "clipping": {"mode": "manual", "manual_plane_normal": [0, 1, 0], "manual_plane_origin": [0, 0, 0]},
            "harmonize": {"n_vertices": 3000, "repair": False},
        },
    )
    assert status == "done"
    results = client.get(f"/api/sessions/{session_id}/results").json()
    assert results["vertex_count"] > 0


def test_results_before_analysis_returns_409(client):
    session_id = _upload(client)
    response = client.get(f"/api/sessions/{session_id}/results")
    assert response.status_code == 409


def test_analyze_rejects_wrong_landmark_count(client):
    session_id = _upload(client)
    response = client.post(
        f"/api/sessions/{session_id}/analyze",
        json={"target": "cranium", "landmarks": [{"x": 0, "y": 0, "z": 0}]},
    )
    assert response.status_code == 422


def test_results_bundle_download(client, landmarks_payload):
    session_id = _upload(client)
    status = _run_analysis(
        client,
        session_id,
        {"target": "cranium", "landmarks": landmarks_payload, "harmonize": {"n_vertices": 3000}},
    )
    assert status == "done"

    bundle = client.get(f"/api/sessions/{session_id}/bundle")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert "CP_template_xy_com_results.zip" in bundle.headers["content-disposition"]

    zf = zipfile.ZipFile(BytesIO(bundle.content))
    names = zf.namelist()
    assert any(n.endswith("_registered.ply") for n in names)
    assert any(n.endswith("_final.ply") for n in names)
    assert any(n.endswith("_report.json") for n in names)
    assert any(n.endswith("_measurements.png") for n in names)


def test_open_mesh_from_paths(client):
    response = client.post("/api/sessions/from-paths", json={"paths": [str(TEMPLATE_PATH)]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertex_count"] > 0


def test_open_mesh_from_paths_missing_file_400s(client):
    response = client.post("/api/sessions/from-paths", json={"paths": ["C:/nope/not-a-real-file.ply"]})
    assert response.status_code == 400


def test_save_results_without_source_dir_400s(client, landmarks_payload):
    # opened via the plain-bytes /api/sessions upload, so there's no known
    # source folder to save into
    session_id = _upload(client)
    status = _run_analysis(client, session_id, {"target": "cranium", "landmarks": landmarks_payload})
    assert status == "done"

    response = client.post(f"/api/sessions/{session_id}/save")
    assert response.status_code == 400


def test_save_results_to_source_folder(client, landmarks_payload, tmp_path):
    import shutil

    tmp_mesh = tmp_path / "1016510_20210730.000112_edited.ply"
    shutil.copy(TEMPLATE_PATH, tmp_mesh)

    open_response = client.post("/api/sessions/from-paths", json={"paths": [str(tmp_mesh)]})
    session_id = open_response.json()["session_id"]

    status = _run_analysis(client, session_id, {"target": "cranium", "landmarks": landmarks_payload})
    assert status == "done"

    save_response = client.post(f"/api/sessions/{session_id}/save")
    assert save_response.status_code == 200, save_response.text
    saved_to = Path(save_response.json()["saved_to"])
    assert saved_to == tmp_path / "CP_1016510_20210730_edited_results"
    assert (saved_to / "1016510_20210730_edited_registered.ply").exists()
    assert (saved_to / "1016510_20210730_edited_final.ply").exists()
    assert (saved_to / "1016510_20210730_edited_report.json").exists()
