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

    # these get filled in as the job runs
    registered_mesh: trimesh.Trimesh | None = None
    result_mesh: trimesh.Trimesh | None = None
    job_status: JobStatus = "idle"
    job_error: str | None = None
    progress: dict[str, str] = field(default_factory=lambda: {"stage": "idle", "detail": ""})
    result: dict[str, Any] | None = None
    _future: Future | None = field(default=None, repr=False)

    def report_progress(self, stage: str, detail: str = "") -> None:
        self.progress = {"stage": stage, "detail": detail}


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
