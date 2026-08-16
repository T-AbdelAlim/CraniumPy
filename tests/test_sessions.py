"""unit tests for api/sessions.py's Session.snapshot_target/restore_target/
switch_active_target - the per-target scene snapshot that lets the frontend
switch between cranial and facial without re-running align/clip/run against
whichever target it switches back to. pure dataclass-field tests, no
FastAPI/pipeline needed - the API-level behavior (the /switch-target
endpoint, and that switching really does skip recomputation) is covered in
tests/test_api.py instead."""

from __future__ import annotations

import trimesh

from api.sessions import Session, _TARGET_SCOPED_DEFAULTS


def _session() -> Session:
    mesh = trimesh.creation.icosphere(subdivisions=1)
    return Session(id="s1", mesh=mesh)


def test_switch_active_target_first_call_is_not_restored():
    session = _session()
    restored = session.switch_active_target("cranium")
    assert restored is False
    assert session.active_target == "cranium"
    assert session.target_snapshots == {}  # nothing to snapshot yet - this was the first target


def test_switch_active_target_redundant_call_reports_restored_and_changes_nothing():
    session = _session()
    session.switch_active_target("cranium")
    session.registered_mesh = session.mesh  # pretend align happened
    session.job_status = "done"

    restored = session.switch_active_target("cranium")
    assert restored is True
    assert session.registered_mesh is session.mesh  # untouched
    assert session.job_status == "done"
    assert session.target_snapshots == {}  # a same-target call never snapshots anything


def test_switch_active_target_snapshots_old_and_resets_never_visited_new_target():
    session = _session()
    session.switch_active_target("cranium")
    session.registered_mesh = session.mesh
    session.used_alt_frontal = True
    session.job_status = "done"
    session.hc_slice_height = 42.0

    restored = session.switch_active_target("face")
    assert restored is False
    assert session.active_target == "face"
    # every target-scoped field reset to its blank default
    assert session.registered_mesh is None
    assert session.used_alt_frontal is False
    assert session.job_status == "idle"
    assert session.hc_slice_height is None
    # the cranium fields it left behind got frozen, not lost
    assert session.target_snapshots["cranium"]["registered_mesh"] is session.mesh
    assert session.target_snapshots["cranium"]["used_alt_frontal"] is True
    assert session.target_snapshots["cranium"]["hc_slice_height"] == 42.0


def test_switch_active_target_restores_a_previously_visited_target_exactly():
    session = _session()
    session.switch_active_target("cranium")
    cranium_mesh = session.mesh.copy()
    session.registered_mesh = cranium_mesh
    session.result_mesh = cranium_mesh
    session.job_status = "done"
    session.hc_slice_height = 17.5

    session.switch_active_target("face")
    session.registered_mesh = None  # face never got aligned
    session.job_status = "idle"

    restored = session.switch_active_target("cranium")
    assert restored is True
    assert session.registered_mesh is cranium_mesh
    assert session.result_mesh is cranium_mesh
    assert session.job_status == "done"
    assert session.hc_slice_height == 17.5


def test_snapshot_target_freezes_values_independent_of_later_mutation():
    session = _session()
    session.switch_active_target("cranium")
    session.hc_slice_height = 10.0
    session.switch_active_target("face")  # snapshots cranium's hc_slice_height=10.0

    # mutate what's now the frontend-invisible cranium snapshot indirectly -
    # by switching back, changing it, and switching away again - to prove
    # each switch away takes a fresh, independent copy rather than sharing
    # a reference that a later mutation could corrupt retroactively.
    session.switch_active_target("cranium")
    assert session.hc_slice_height == 10.0
    session.hc_slice_height = 99.0
    session.switch_active_target("face")

    session.switch_active_target("cranium")
    assert session.hc_slice_height == 99.0


def test_restore_target_return_value_matches_whether_a_snapshot_existed():
    session = _session()
    assert session.restore_target("cranium") is False
    session.target_snapshots["cranium"] = {name: default for name, default in _TARGET_SCOPED_DEFAULTS.items()}
    assert session.restore_target("cranium") is True


def test_restore_target_clears_nicp_preview_mesh_regardless_of_snapshot():
    session = _session()
    session.nicp_preview_mesh = session.mesh
    session.restore_target("cranium")
    assert session.nicp_preview_mesh is None
