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


def test_trends_export_writes_png_and_xlsx_into_a_named_folder(client, tmp_path):
    # the Trends tab's one "export results" button - unlike every endpoint
    # above, this one needs no session/mesh at all: the frontend already
    # has the measurement values, this is purely "write these into a
    # folder" (see api/results_bundle.trends_chart_png for the figure,
    # api/routers/cohort._build_export_xlsx for the sheet).
    response = client.post(
        "/api/longitudinal/trends-export",
        json={
            "x_labels": ["Timepoint 0", "Timepoint 1"],
            "series": [
                {"label": "OFD (head length)", "unit": "mm", "color": "#16a34a", "values": [180.0, 185.0]},
                {"label": "Ridge protrusion", "unit": "mm", "color": "#dc2626", "values": [None, 2.5]},
            ],
            "dest_dir": str(tmp_path),
            "folder_name": "patient1_trend_t0_t1",
        },
    )

    assert response.status_code == 200, response.text
    saved_to = Path(response.json()["saved_to"])
    assert saved_to == tmp_path / "patient1_trend_t0_t1"
    names = {p.name for p in saved_to.iterdir()}
    assert names == {"measurements_over_time.png", "measurements_over_time.xlsx"}
    assert (saved_to / "measurements_over_time.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_trends_export_not_a_real_folder_is_a_clear_error(client):
    response = client.post(
        "/api/longitudinal/trends-export",
        json={"x_labels": ["Timepoint 0"], "series": [], "dest_dir": "C:/nope/not-a-real-folder", "folder_name": "x"},
    )
    assert response.status_code == 400


def test_save_video_writes_bytes_into_a_named_folder(client, tmp_path):
    response = client.post(
        "/api/longitudinal/save-video",
        data={"dest_dir": str(tmp_path), "folder_name": "patient1_morph_t0_t2", "extension": "webm"},
        files={"video": ("morph_animation.webm", b"not-really-a-video-but-fine-for-this-test", "video/webm")},
    )

    assert response.status_code == 200, response.text
    saved_to = Path(response.json()["saved_to"])
    assert saved_to == tmp_path / "patient1_morph_t0_t2"
    assert (saved_to / "morph_animation.webm").read_bytes() == b"not-really-a-video-but-fine-for-this-test"


def _post_video(client, tmp_path, payload=b"clip", **extra):
    return client.post(
        "/api/longitudinal/save-video",
        data={"dest_dir": str(tmp_path), "folder_name": "p_morph_t0_t1", "extension": "webm", **extra},
        files={"video": ("x.webm", payload, "video/webm")},
    )


def test_save_video_adds_overlay_suffix_to_filename(client, tmp_path):
    response = _post_video(client, tmp_path, suffix="asymmetry")

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "morph_animation_asymmetry.webm"
    assert (tmp_path / "p_morph_t0_t1" / "morph_animation_asymmetry.webm").exists()


def test_save_video_existing_file_asks_instead_of_overwriting(client, tmp_path):
    assert _post_video(client, tmp_path, payload=b"first", suffix="none").status_code == 200

    response = _post_video(client, tmp_path, payload=b"second", suffix="none")

    assert response.status_code == 409
    assert response.json()["detail"] == {"exists": True, "filename": "morph_animation_none.webm"}
    assert (tmp_path / "p_morph_t0_t1" / "morph_animation_none.webm").read_bytes() == b"first"


def test_save_video_overwrite_replaces_the_file(client, tmp_path):
    _post_video(client, tmp_path, payload=b"first", suffix="none")

    response = _post_video(client, tmp_path, payload=b"second", suffix="none", on_conflict="overwrite")

    assert response.status_code == 200
    assert (tmp_path / "p_morph_t0_t1" / "morph_animation_none.webm").read_bytes() == b"second"


def test_save_video_rename_keeps_both_files(client, tmp_path):
    _post_video(client, tmp_path, payload=b"first", suffix="none")
    _post_video(client, tmp_path, payload=b"second", suffix="none", on_conflict="rename")

    response = _post_video(client, tmp_path, payload=b"third", suffix="none", on_conflict="rename")

    folder = tmp_path / "p_morph_t0_t1"
    assert response.json()["filename"] == "morph_animation_none_3.webm"
    assert (folder / "morph_animation_none.webm").read_bytes() == b"first"
    assert (folder / "morph_animation_none_2.webm").read_bytes() == b"second"
    assert (folder / "morph_animation_none_3.webm").read_bytes() == b"third"


def _heatmap_request(tmp_path, templates, **extra):
    return {
        "stages": [
            {"ref": {"template": name}, "label": f"Timepoint {i}", "index": i} for i, name in enumerate(templates)
        ],
        "dest_dir": str(tmp_path),
        "folder_name": "p_morph_t0_t2",
        **extra,
    }


def test_heatmap_figures_writes_n_minus_one_pngs_into_a_heatmaps_folder(client, tmp_path):
    response = client.post(
        "/api/longitudinal/heatmap-figures",
        json=_heatmap_request(tmp_path, ["clipped_template_xy"] * 3),
    )

    assert response.status_code == 200, response.text
    folder = tmp_path / "p_morph_t0_t2" / "heatmaps"
    assert Path(response.json()["saved_to"]) == folder
    assert response.json()["files"] == ["heatmap_t0_to_t1.png", "heatmap_t1_to_t2.png"]
    assert sorted(p.name for p in folder.iterdir()) == response.json()["files"]
    assert (folder / "heatmap_t0_to_t1.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_heatmap_figures_needs_at_least_two_stages(client, tmp_path):
    response = client.post(
        "/api/longitudinal/heatmap-figures", json=_heatmap_request(tmp_path, ["clipped_template_xy"])
    )

    assert response.status_code == 400


def test_heatmap_figures_topology_mismatch_is_a_clear_error(client, tmp_path):
    response = client.post(
        "/api/longitudinal/heatmap-figures",
        json=_heatmap_request(tmp_path, ["clipped_template_xy", "template_face"]),
    )

    assert response.status_code == 400
