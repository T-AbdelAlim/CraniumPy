"""mesh repair in a worker process.

pymeshfix holds the GIL for its whole run - about 20s on a real scan - so a
repair on one of the server's own threads froze every other request for
that long: the progress bar stopped polling, the clip preview didn't draw,
the viewer couldn't fetch a mesh. a separate process has its own
interpreter, so the server keeps answering while it works.

one worker, started on the first upload (see warm_up) so its interpreter
and imports are ready by the time a repair is needed. anything that keeps
the pool from working - a platform that can't spawn processes, a worker
that died - falls back to repairing in-process, exactly as before, just
without the responsiveness.
"""

from __future__ import annotations

import multiprocessing
import pickle
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import numpy as np
import trimesh

_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _repair_arrays(
    vertices: np.ndarray,
    faces: np.ndarray,
    landmarks: np.ndarray,
    alt_frontal: np.ndarray | None,
    repair_method: str,
    clip_mode: str | None,
) -> tuple[np.ndarray, np.ndarray]:
    # bare arrays both ways: rough_bounding_clip and repair_mesh both start
    # from vertices/faces alone (texture never survives a repair), and
    # arrays are far cheaper to send between processes than a Trimesh.
    from craniumpy_core import pipeline

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if clip_mode != "manual":
        mesh = pipeline.rough_bounding_clip(mesh, landmarks, alt_frontal_landmark=alt_frontal)
    repaired = pipeline.repair_mesh(mesh, method=repair_method)
    return np.asarray(repaired.vertices), np.asarray(repaired.faces)


def _ready() -> bool:
    from craniumpy_core import pipeline  # noqa: F401 - the import is the point

    return True


def _get_pool() -> ProcessPoolExecutor | None:
    global _pool
    # a daemonic process (a multiprocessing pool worker running the API,
    # say - a batch script) isn't allowed to start children of its own
    if multiprocessing.current_process().daemon:
        return None
    with _pool_lock:
        if _pool is None:
            try:
                _pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
            except (OSError, NotImplementedError, ValueError):
                return None
        return _pool


def _discard_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def warm_up() -> None:
    """starts the worker and its imports in the background - called when a
    mesh is opened, so the first repair doesn't also pay for that."""
    pool = _get_pool()
    if pool is None:
        return
    try:
        pool.submit(_ready)
    except Exception:  # noqa: BLE001 - only a head start; repair() handles a broken pool itself
        _discard_pool()


def repair(
    mesh: trimesh.Trimesh,
    landmarks: np.ndarray,
    alt_frontal: np.ndarray | None,
    repair_method: str,
    clip_mode: str | None,
) -> trimesh.Trimesh:
    """the rough landmark crop plus repair (see api/routers/mesh.py's
    _build_repair), run in the worker process. blocks the calling thread
    until it's done, but without holding the GIL while it waits."""
    args = (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int64),
        np.asarray(landmarks, dtype=np.float64),
        None if alt_frontal is None else np.asarray(alt_frontal, dtype=np.float64),
        repair_method,
        clip_mode,
    )
    pool = _get_pool()
    if pool is not None:
        # only a worker that couldn't do the job at all is a reason to fall
        # back - an error from the repair itself is raised as it would be
        # in-process.
        try:
            future = pool.submit(_repair_arrays, *args)
        except Exception:  # noqa: BLE001 - shut down, or the worker couldn't be started at all
            future = None
            _discard_pool()
        if future is not None:
            try:
                vertices, faces = future.result()
                return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            except (BrokenProcessPool, OSError, pickle.PicklingError):
                _discard_pool()
    vertices, faces = _repair_arrays(*args)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
