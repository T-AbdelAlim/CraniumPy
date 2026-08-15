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
        self.result = None

    def report_progress(self, stage: str, detail: str = "", current: int | None = None, total: int | None = None) -> None:
        self.progress = {"stage": stage, "detail": detail, "current": current, "total": total}


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
