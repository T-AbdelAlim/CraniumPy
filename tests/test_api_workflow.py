"""going back and forth through the per-patient pipeline: switching target
after a run, re-aligning with changed picks, and staging a fit for
Longitudinal while the patient session carries on changing."""

from __future__ import annotations

import numpy as np
import pytest

from api.sessions import store
from craniumpy_core import pipeline
from tests.test_api import _clip_and_run, _run_align, _run_run, _upload


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


@pytest.fixture
def landmarks_payload():
    from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE

    return [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in REFERENCE_TRIANGLE]


def _switch(client, session_id: str, target: str) -> dict:
    response = client.post(f"/api/sessions/{session_id}/switch-target", json={"target": target})
    assert response.status_code == 200, response.text
    return response.json()


def _wait_for_prefetch(session_id: str) -> None:
    for future in list(store.get(session_id)._repair_pending.values()):
        future.result(timeout=60)


def test_switching_target_reuses_the_repair_instead_of_running_it_again(client, landmarks_payload, monkeypatch):
    from api.routers import mesh as mesh_router

    calls = []
    real_build = mesh_router._build_repair

    def counting_build(mesh, landmarks, alt_frontal, repair_method, clip_mode):
        calls.append(repair_method)
        return real_build(mesh, landmarks, alt_frontal, repair_method, clip_mode)

    monkeypatch.setattr(mesh_router, "_build_repair", counting_build)
    session_id = _upload(client)

    _switch(client, session_id, "face")
    assert _run_align(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"

    _switch(client, session_id, "cranium")
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    _wait_for_prefetch(session_id)

    # once for the picks - the prefetch /align starts and both clips share it
    assert calls == ["pymeshfix"]


def test_align_prefetches_the_repair_the_clip_will_need(client, landmarks_payload):
    session_id = _upload(client)
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    session = store.get(session_id)
    assert len(session._repair_pending) == 1
    prefetched = next(iter(session._repair_pending.values())).result(timeout=60)

    assert _clip_and_run(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert list(session.repair_cache.values()) == [prefetched]
    assert not session._repair_pending


def test_other_targets_scene_survives_a_realign_with_the_same_picks(client, landmarks_payload):
    session_id = _upload(client)
    _switch(client, session_id, "face")
    assert _run_align(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"

    _switch(client, session_id, "cranium")
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"

    restored = _switch(client, session_id, "face")
    assert restored["restored"] is True
    assert restored["pipeline_ran"] is True


def test_other_targets_scene_is_dropped_once_the_picks_move(client, landmarks_payload):
    session_id = _upload(client)
    _switch(client, session_id, "face")
    assert _run_align(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "face", "landmarks": landmarks_payload}) == "done"

    moved = [dict(p) for p in landmarks_payload]
    moved[0]["y"] += 3.0
    _switch(client, session_id, "cranium")
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": moved}) == "done"

    # the face result was built from the old sellion - it must not come back
    switched = _switch(client, session_id, "face")
    assert switched["restored"] is False
    assert switched["pipeline_ran"] is False


def test_realign_after_a_run_goes_back_to_the_clip_step(client, landmarks_payload):
    session_id = _upload(client)
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"

    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert client.get(f"/api/sessions/{session_id}/mesh/result").status_code == 409
    assert client.get(f"/api/sessions/{session_id}/clip-preview?target=cranium").status_code == 200


def test_freeze_nicp_needs_a_fit(client, landmarks_payload):
    session_id = _upload(client)
    assert client.post(f"/api/sessions/{session_id}/freeze-nicp").status_code == 409


def test_frozen_fit_outlives_changes_to_the_patient_session(client, landmarks_payload):
    session_id = _upload(client)
    assert _run_align(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert _clip_and_run(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    nicp = {"template": "clipped_template_xy", "alpha_start": 50, "alpha_end": 10, "alpha_steps": 2, "inner_iters": 1}
    assert _run_run(client, session_id, {"n_vertices": None, "nicp": nicp}, timeout=120) == "done"
    fitted = np.asarray(store.get(session_id).nicp_result_mesh.vertices).copy()

    response = client.post(f"/api/sessions/{session_id}/freeze-nicp")
    assert response.status_code == 200, response.text
    frozen_id = response.json()["session_id"]
    assert frozen_id != session_id

    # what used to empty a staged timepoint: a re-run clears the live fit,
    # and the patient session gets closed for the next upload
    assert _clip_and_run(client, session_id, {"target": "cranium", "landmarks": landmarks_payload}) == "done"
    assert client.get(f"/api/sessions/{session_id}/mesh/nicp-result").status_code == 409
    client.delete(f"/api/sessions/{session_id}")

    assert client.get(f"/api/sessions/{frozen_id}/mesh/nicp-result").status_code == 200
    assert np.allclose(store.get(frozen_id).nicp_result_mesh.vertices, fitted)
    measured = client.post(
        "/api/longitudinal/measure", json={"ref": {"session_id": frozen_id, "stage": "nicp_result"}, "target": "cranium"}
    )
    assert measured.status_code == 200, measured.text


def test_worker_repair_matches_an_in_process_repair():
    from api import repair_worker
    from craniumpy_core.io import load_mesh
    from craniumpy_core.registration.rigid import REFERENCE_TRIANGLE
    from tests.test_api import TEMPLATE_PATH

    mesh = load_mesh(TEMPLATE_PATH)
    landmarks = np.asarray(REFERENCE_TRIANGLE, dtype=np.float64)
    in_worker = repair_worker.repair(mesh, landmarks, None, "pymeshfix", None)
    in_process = pipeline.repair_mesh(pipeline.rough_bounding_clip(mesh, landmarks), method="pymeshfix")
    assert np.array_equal(np.asarray(in_worker.faces), np.asarray(in_process.faces))
    assert np.array_equal(np.asarray(in_worker.vertices), np.asarray(in_process.vertices))
