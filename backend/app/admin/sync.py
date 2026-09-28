"""Runs the Blackboard sync script for the admin panel: one job at a time, as a subprocess, with its
events, a run history in backend/data/sync-runs.json, and an automatic sync every sync_auto_days days."""

import datetime as dt
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import ROOT, get_settings
from ..sync.blackboard import DATA_DIR, STATE_FILE

log = logging.getLogger(__name__)

MODES = {
    "sync": ["--headless"],
    "preview": ["--headless", "--dry-run"],
    "probe": ["--headless", "--probe"],
    "login": ["--probe"],  # visible window: the user logs in
}
COUNTED = ("downloaded", "saved_page", "already_had", "would_download", "would_save_page", "failed")
KEEP_EVENTS = 200
KEEP_RUNS = 20
SUMMARY = ("id", "mode", "course", "started_at", "finished_at", "state", "exit_code", "counts", "bytes", "error")


class Busy(RuntimeError):
    pass


def _iso(ts: float | None) -> str | None:
    return None if ts is None else dt.datetime.fromtimestamp(ts, dt.UTC).isoformat()


def modules() -> list[str]:
    inbox = get_settings().inbox
    return sorted(p.name for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []


class SyncRunner:
    def __init__(self, command: list[str] | None = None, runs_file: Path = DATA_DIR / "sync-runs.json",
                 state_file: Path = STATE_FILE, clock=time.time):
        self.command = command or [sys.executable, "-m", "app.sync.blackboard"]
        self.runs_file = runs_file
        self.state_file = state_file
        self.clock = clock
        self.job: dict | None = None
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None

    # --- history ---------------------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(self.runs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"runs": [], "login_needed": False}

    def _save(self, data: dict) -> None:
        self.runs_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.runs_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.runs_file)

    def login_needed(self) -> bool:
        return bool(self._load().get("login_needed"))

    def last_full_sync(self) -> float | None:
        """The last ok full sync from the panel, or the state file's mtime (the command line writes it too)."""
        times = [r["finished_at"] for r in self._load()["runs"]
                 if r["mode"] == "sync" and not r["course"] and r["state"] == "ok"]
        if self.state_file.exists():
            times.append(self.state_file.stat().st_mtime)
        return max(times, default=None)

    # --- the job ---------------------------------------------------------------------------------
    def running(self) -> bool:
        return self.job is not None and self.job["state"] == "running"

    def start(self, mode: str, course: str | None = None) -> dict:
        with self._lock:
            if self.running():
                raise Busy("a sync is already running")
            args = [*self.command, "--json", *MODES[mode], *(["--course", course] if course else [])]
            self._proc = subprocess.Popen(
                args, cwd=ROOT / "backend", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.job = {"id": int(self.clock() * 1000), "mode": mode, "course": course,
                        "started_at": self.clock(), "finished_at": None, "state": "running", "exit_code": None,
                        "counts": dict.fromkeys(COUNTED, 0), "bytes": 0, "error": None, "events": [],
                        "courses": None, "cancelled": False}
            self._reader = threading.Thread(target=self._read, args=(self._proc, self.job), daemon=True)
            self._reader.start()
            return self._view(self.job)

    def _read(self, proc: subprocess.Popen, job: dict) -> None:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                ev = None
            if not isinstance(ev, dict):
                ev = {"type": "log", "text": line}
            with self._lock:
                job["events"] = [*job["events"], ev][-KEEP_EVENTS:]
                kind = ev.get("type")
                if kind == "file" and ev.get("action") in job["counts"]:
                    job["counts"][ev["action"]] += 1
                elif kind == "courses":
                    job["courses"] = ev.get("courses")
                elif kind == "done":
                    job["bytes"] = ev.get("bytes", 0)
                elif kind == "error":
                    job["error"] = ev.get("message")
        code = proc.wait()
        with self._lock:
            job["exit_code"] = code
            job["finished_at"] = self.clock()
            job["state"] = ("cancelled" if job["cancelled"] else "ok" if code == 0
                            else "login_required" if code == 3 else "failed")
            data = self._load()
            data["runs"] = [{k: job[k] for k in SUMMARY}, *data["runs"]][:KEEP_RUNS]
            if job["state"] == "login_required":
                data["login_needed"] = True
            elif job["state"] == "ok":
                data["login_needed"] = False
            self._save(data)
        log.info("blackboard %s finished: %s", job["mode"], job["state"])

    def wait(self, timeout: float = 30) -> None:
        if self._reader:
            self._reader.join(timeout)

    def cancel(self) -> dict | None:
        with self._lock:
            if not self.running():
                return None
            self.job["cancelled"] = True
            proc = self._proc
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.wait(10)
        return self._view(self.job)

    # --- schedule --------------------------------------------------------------------------------
    def due(self, now: float | None = None) -> bool:
        days = get_settings().sync_auto_days
        if days <= 0 or self.running() or self.login_needed():
            return False
        last = self.last_full_sync()
        return last is None or (now or self.clock()) - last >= days * 86_400

    def next_auto(self) -> str | None:
        days = get_settings().sync_auto_days
        if days <= 0 or self.running() or self.login_needed():
            return None
        last = self.last_full_sync()
        now = self.clock()
        return _iso(now if last is None else max(now, last + days * 86_400))

    # --- views -----------------------------------------------------------------------------------
    @staticmethod
    def _view(job: dict) -> dict:
        v = {k: val for k, val in job.items() if k != "cancelled"}
        v["started_at"], v["finished_at"] = _iso(job["started_at"]), _iso(job["finished_at"])
        if "events" in job:
            v["events"] = list(job["events"])
        return v

    def status(self) -> dict:
        data = self._load()
        with self._lock:
            job = self._view(self.job) if self.job else None
        return {
            "job": job,
            "runs": [self._view(r) for r in data["runs"]],
            "login_needed": bool(data.get("login_needed")),
            "last_full_sync": _iso(self.last_full_sync()),
            "next_auto": self.next_auto(),
            "auto_days": get_settings().sync_auto_days,
            "modules": modules(),
        }


runner = SyncRunner()


class AutoSync:
    """Checks every hour (first check a few minutes after startup) whether a full sync is due, and starts it."""

    def __init__(self, first_delay: float = 300, every: float = 3600):
        self.first_delay, self.every = first_delay, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="blackboard-autosync", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(self.first_delay):
            return
        while True:
            try:
                if runner.due():
                    log.info("blackboard auto-sync is due; starting")
                    runner.start("sync")
            except Busy:
                pass
            except Exception:  # a failed check must not kill the scheduler thread
                log.exception("auto-sync check failed")
            if self._stop.wait(self.every):
                return
