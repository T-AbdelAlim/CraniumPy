"""in-memory session store - one uploaded mesh + whatever state it's in, per
session. actual pipeline work runs on a background thread pool so the
request doesn't just hang there for minutes.

kept this deliberately simple, no redis/celery/database. this is a
single-process tool (either the desktop app or a small internal web
service), not something that needs to scale out. see DEPENDENCIES.md if
curious why.

sessions just disappear if the process restarts. that's fine - a session is
"the mesh I'm currently working on", not something that needs to survive a
restart.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
import trimesh

JobStatus = Literal["idle", "running", "done", "error"]

_executor = ThreadPoolExecutor(max_workers=2)

# every Session field whose value describes "the align/clip/run pipeline for
# THIS target", as opposed to the raw uploaded mesh itself - swapped out
# wholesale by Session.snapshot_target/restore_target whenever the frontend
# switches between cranial and facial, so returning to a target already
# processed this session shows exactly the scene left behind (no re-running
# align/clip/run against it). keyed by field name -> the value a target that
# was never visited resets to. progress's dict is never mutated in place
# (report_progress always reassigns a fresh one - see below), so sharing this
# one default object across resets is safe.
_TARGET_SCOPED_DEFAULTS: dict[str, Any] = {
    "repaired_mesh": None,
    "repaired_mesh_cache_key": None,
    "sellion_registered_mesh": None,
    "sellion_registered_landmarks": None,
    "registered_mesh": None,
    "registered_landmarks": None,
    "registered_transform": None,
    "aligned_mesh": None,
    "sellion_clipped_mesh": None,
    "clipped_mesh": None,
    "used_alt_frontal": False,
    "last_clip_config": None,
    "result_mesh": None,
    "sellion_result_mesh": None,
    "nicp_result_mesh": None,
    "last_nicp_config": None,
    "hc_slice_height": None,
    "job_status": "idle",
    "job_error": None,
    "progress": {"stage": "idle", "detail": ""},
    "result": None,
}


@dataclass
class Session:
    id: str
    mesh: trimesh.Trimesh
    original_filename: str = "mesh"
    # set only when the mesh was opened from a real local path (desktop
    # app's native file picker, not a browser upload) - lets /save write
    # results straight next to the original file instead of needing a
    # browser download. see api/routers/mesh.py's open_mesh_from_paths.
    source_dir: Path | None = None

    # repair is orientation-invariant (see pipeline.register_and_clip_cranial's
    # docstring), so it's cached here across repeated /clip calls instead of
    # re-running pymeshfix - the single most expensive step - on every plane
    # tweak. what actually gets repaired is a rough, landmark-based pre-clip
    # of the raw mesh now (see pipeline.rough_bounding_clip), not the raw
    # mesh itself, so the cache key has to cover the landmarks/alt-frontal/
    # target/clip-mode that crop depends on too, not just repair_method -
    # rebuilt whenever repaired_mesh_cache_key no longer matches.
    repaired_mesh: trimesh.Trimesh | None = None
    repaired_mesh_cache_key: tuple | None = None

    # set first by /align (raw mesh, no repair/CoM), then overwritten by
    # /clip with the repaired + (optionally) CoM-nudged version it actually
    # clips from - this is the pre-clip (registered) state, kept around for
    # /clip/undo and for measure_cranial's alt-frame procrustes_fit
    # correspondence, not just the post-clip result. see aligned_mesh below
    # for the value that survives the /clip overwrite.
    sellion_registered_mesh: trimesh.Trimesh | None = None
    sellion_registered_landmarks: np.ndarray | None = None
    registered_mesh: trimesh.Trimesh | None = None  # display-frame pre-clip mesh (== sellion's when no alt frontal)
    registered_landmarks: np.ndarray | None = None
    # the RigidTransform (rotation + translation) that produced
    # registered_mesh/registered_landmarks above, from the last successful
    # /align - lets the frontend convert a landmark position between raw
    # and aligned coordinates for "adjust picks" without re-deriving the
    # fit client-side. typed loosely (Any) to avoid api.sessions
    # depending on craniumpy_core.registration.rigid.
    registered_transform: Any | None = None
    # the pure /align output - raw mesh, landmark-triangle rigid transform
    # only, no repair, no center-of-mass nudge, no clip. registered_mesh
    # above gets overwritten by /clip with a repaired + (optionally)
    # CoM-nudged version for the actual pipeline, so this is kept as its
    # own field specifically so the saved _rg.ply still reflects what
    # "align" actually produced. set by /align, untouched by /clip.
    aligned_mesh: trimesh.Trimesh | None = None

    # post repair+clip+boundary-cleanup, pre-resample - what /clip actually
    # produces. cleared (along with everything below) by /clip or
    # /clip/undo, since anything downstream is stale the moment the clip
    # changes.
    sellion_clipped_mesh: trimesh.Trimesh | None = None
    clipped_mesh: trimesh.Trimesh | None = None
    # only meaningful for target="cranium" - whether the clip above used an
    # alt_frontal_landmark, i.e. whether sellion_clipped_mesh/clipped_mesh
    # are actually two different meshes or the same one twice.
    used_alt_frontal: bool = False

    # the api.schemas.ClipRequest that produced the state above - kept as-is
    # (not broken into a dict) so /run can read its fields directly and
    # reconstruct an AnalyzeRequest-shaped object for the bundle/save
    # report. typed loosely (Any) to avoid api.sessions depending on
    # api.schemas.
    last_clip_config: Any | None = None

    # final, post-resample - what /run produces.
    result_mesh: trimesh.Trimesh | None = None
    # only set for cranial analyses that used an alt_frontal_landmark -
    # result_mesh becomes the alt-frame mesh in that case (see
    # api/routers/mesh.py's run_analysis), so this is the one place the
    # sellion-frame mesh survives, for the always-sellion-oriented saved 2D
    # figure (see api/results_bundle.py's _measurement_figure).
    sellion_result_mesh: trimesh.Trimesh | None = None
    # only set once a NICP fit ("fit template") has completed - deliberately
    # independent of result_mesh, not a copy of it: a template-deformed
    # mesh describes the template's shape approximating this patient, not
    # this patient's own actual anatomy, so a fit never touches
    # result_mesh/craniometrics/asymmetry (see /run's handler) - it only
    # ever adds this one extra artifact, which becomes the third
    # _rg_{C|F}N.ply file on save (see api/results_bundle.py) alongside the
    # normal two, unconditionally on top of whatever result_mesh already
    # is. cleared by clear_clip_result() (a fresh clip invalidates any
    # prior fit) and by a plain (non-NICP) /run.
    nicp_result_mesh: trimesh.Trimesh | None = None
    # the api.schemas.NicpConfig that produced nicp_result_mesh above - None
    # whenever nicp_result_mesh is, kept as its own field (not read back out
    # of the RunRequest that triggered it) purely so the save/export
    # endpoints can report which template a fit actually used without
    # threading a whole RunRequest through them. typed loosely (Any) to
    # avoid api.sessions depending on api.schemas, same reasoning as
    # last_clip_config above.
    last_nicp_config: Any | None = None
    # facial-target only - the HC slice height (in this session's facial
    # registration frame), computed once by /clip via
    # pipeline.hc_slice_height_facial_frame and reused by /run's metopic
    # analysis, so both always describe the literal same plane a cranial
    # run on this same patient would have used - see
    # craniumpy_core.metopic's module docstring. None for cranial-target
    # sessions (extract_measurements finds its own slice height inline, as
    # it always has) or before /clip has run.
    hc_slice_height: float | None = None
    # which target (cranium/face) the fields above currently describe - set
    # by /align and /clip's own _run closures, and by switch_active_target
    # below. None only before the first /align or /clip of a fresh session.
    active_target: str | None = None
    # one frozen copy of every _TARGET_SCOPED_DEFAULTS field per target
    # that's been switched away from, populated by snapshot_target and
    # applied by restore_target - see switch_active_target, the single
    # entry point both api/routers/mesh.py's /switch-target endpoint and
    # /align and /clip go through so this never gets out of sync with
    # active_target.
    target_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    job_status: JobStatus = "idle"
    job_error: str | None = None
    progress: dict[str, Any] = field(default_factory=lambda: {"stage": "idle", "detail": ""})
    result: dict[str, Any] | None = None
    # the current in-progress NICP fit's deformed template, updated live via
    # on_nicp_preview as the fit runs - lets /mesh/nicp-preview serve
    # something to poll for the "watch it deform" live view. stale once the
    # fit finishes (numerically equal to the final result_mesh's own frame
    # by then), harmless to leave around until the next run_job clears it.
    nicp_preview_mesh: trimesh.Trimesh | None = None
    _future: Future | None = field(default=None, repr=False)

    def clear_clip_result(self) -> None:
        """reverts everything from the clip stage onward - used by both a
        fresh /clip call (whatever the previous clip produced is stale)
        and /clip/undo (go back to just the registered mesh)."""
        self.sellion_clipped_mesh = None
        self.clipped_mesh = None
        self.used_alt_frontal = False
        self.result_mesh = None
        self.sellion_result_mesh = None
        self.nicp_result_mesh = None
        self.last_nicp_config = None
        self.hc_slice_height = None
        self.result = None

    def report_progress(self, stage: str, detail: str = "", current: int | None = None, total: int | None = None) -> None:
        self.progress = {"stage": stage, "detail": detail, "current": current, "total": total}

    def snapshot_target(self, target: str) -> None:
        """freezes every _TARGET_SCOPED_DEFAULTS field's current value under
        `target`, so restore_target can bring back the exact same align/clip/
        run state later with zero recomputation."""
        self.target_snapshots[target] = {name: getattr(self, name) for name in _TARGET_SCOPED_DEFAULTS}

    def restore_target(self, target: str) -> bool:
        """loads `target`'s previously snapshotted fields back into place, or
        resets them to blank ("never run") defaults if this target has no
        snapshot yet - either way, nothing gets recomputed here. returns
        whether a snapshot actually existed."""
        snapshot = self.target_snapshots.get(target)
        if snapshot is not None:
            for name, value in snapshot.items():
                setattr(self, name, value)
        else:
            for name, default in _TARGET_SCOPED_DEFAULTS.items():
                setattr(self, name, default)
        self.nicp_preview_mesh = None
        return snapshot is not None

    def switch_active_target(self, new_target: str) -> bool:
        """the one place a target switch actually happens: snapshots
        whatever's currently active (if it differs from new_target) before
        restoring/resetting new_target's own state. safe to call redundantly
        (new_target == active_target already) - just a no-op that reports
        the target as already active."""
        if self.active_target == new_target:
            return True
        if self.active_target is not None:
            self.snapshot_target(self.active_target)
        restored = self.restore_target(new_target)
        self.active_target = new_target
        return restored


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self, mesh: trimesh.Trimesh, original_filename: str = "mesh", source_dir: Path | None = None
    ) -> Session:
        session = Session(
            id=str(uuid.uuid4()), mesh=mesh, original_filename=original_filename, source_dir=source_dir
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def run_job(self, session: Session, fn: Callable[[], dict[str, Any]]) -> None:
        if session.job_status == "running":
            raise RuntimeError("a job is already running for this session")
        session.job_status = "running"
        session.job_error = None
        session.result = None
        session.nicp_preview_mesh = None
        session.report_progress("starting", "")

        def _wrapped() -> None:
            try:
                session.result = fn()
                session.job_status = "done"
                session.report_progress("done", "")
            except Exception as exc:  # noqa: BLE001 - want the client to see whatever went wrong
                session.job_error = str(exc)
                session.job_status = "error"

        session._future = _executor.submit(_wrapped)


store = SessionStore()
