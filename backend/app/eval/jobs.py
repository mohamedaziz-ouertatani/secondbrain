"""One evaluation job at a time (generate or run), in a background thread, sharing the index-job slot."""

import threading
import time

from ..api import jobs as index_jobs
from ..db import get_pool
from . import generate, run


class Busy(RuntimeError):
    pass


_lock = threading.Lock()
_state: dict | None = None
_thread: threading.Thread | None = None
_cancel = threading.Event()


def _work(kind: str, n: int) -> None:
    def progress(done: int, total: int) -> None:
        with _lock:
            _state.update(done=done, total=total)

    try:
        if kind == "generate":
            result = generate.generate(n=n, progress=progress, cancelled=_cancel.is_set)
        else:
            result = {"run_id": run.run(kind=kind, progress=progress, cancelled=_cancel.is_set)}
        with _lock:
            _state.update(state="cancelled" if _cancel.is_set() else "ok", result=result)
    except Exception as e:  # noqa: BLE001 -- reported to the page; the slot is released below
        with _lock:
            _state.update(state="failed", error=str(e))
    finally:
        with _lock:
            _state["finished_at"] = time.time()
        index_jobs.release()


def start(kind: str, n: int = 150) -> dict:
    global _state, _thread
    if not index_jobs.try_acquire():
        raise Busy("a rescan, re-index or evaluation job is already running")
    _cancel.clear()
    with _lock:
        _state = {"kind": kind, "state": "running", "done": 0, "total": 0, "started_at": time.time(),
                  "finished_at": None, "result": None, "error": None}
    _thread = threading.Thread(target=_work, args=(kind, n), name=f"eval-{kind}", daemon=True)
    _thread.start()
    return dict(_state)


def cancel() -> dict | None:
    with _lock:
        if not _state or _state["state"] != "running":
            return None
    _cancel.set()
    wait(60)
    return dict(_state)


def wait(timeout: float = 30) -> None:
    if _thread:
        _thread.join(timeout)


def status() -> dict:
    with get_pool().connection() as conn:
        generated = conn.execute("SELECT count(*) AS n FROM eval_questions").fetchone()["n"]
        runs = conn.execute("SELECT id, ts, kind, params, metrics FROM eval_runs ORDER BY id DESC LIMIT 10").fetchall()
        latest = conn.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    with _lock:
        job = dict(_state) if _state else None
    return {"questions": {"generated": generated, "labelled": 0}, "job": job, "runs": runs, "latest": latest}
