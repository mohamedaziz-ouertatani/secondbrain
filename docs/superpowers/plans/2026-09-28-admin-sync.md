# Admin Panel Part 3 (Blackboard Sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Blackboard sync from `/admin` (sync all, one module, preview, course mapping, log in, cancel) with live progress, keep a run history, and sync automatically every `sync_auto_days` days.

**Architecture:** `app/sync/blackboard.py` sends events through an `emit` callback. `print_event` keeps today's text, and `--json` prints one JSON event per line. `app/admin/sync.py` runs the script as a subprocess, one job at a time. A reader thread folds its events into the job's state, finished runs go to `backend/data/sync-runs.json`, and an `AutoSync` thread started in the lifespan decides when a sync is due. The routes live in `app/api/admin.py`. A new `SyncCard` sits on `/admin`, and the rail footer shows when a login is needed.

**Tech Stack:** Python `subprocess` and `threading`, FastAPI, pytest (a fake sync script for the runner), Next.js 16 client components, plain CSS.

**Spec:** `docs/superpowers/specs/2026-09-28-admin-sync-design.md`

## Global Constraints

- The sync never runs inside the backend process. It is always `python -m app.sync.blackboard --json …` as a subprocess, one job at a time (409 otherwise).
- Mode flags: `sync` → `--headless`; `preview` → `--headless --dry-run`; `probe` → `--headless --probe`; `login` → `--probe`, with no `--headless` so a window opens.
- Exit codes: 0 means ok, 3 means login required, anything else means failed.
- `login_needed` is set by an exit code of 3 and cleared by any `ok` run.
- The runs file keeps the last 20 runs, without events. A live job keeps its last 200 events.
- `sync_auto_days` defaults to 7 and ranges 0–30, where 0 turns auto-sync off. The first automatic check comes 300 s after startup, then one every 3600 s.
- The command line's text output must stay exactly as it is, because the existing tests check its lines.
- Browser checks against the real Blackboard session happen only after the user says go. A full sync and a login are for the user to trigger.
- Postgres is on 5433. Backend commands run from `backend/` with `uv run`. Frontend checks: `npx tsc --noEmit` and `npm run lint`.

---

### Task 1: Events in the sync script

**Files:**
- Modify: `backend/app/sync/blackboard.py`
- Test: `backend/tests/test_blackboard.py` (new tests appended; existing ones unchanged)

**Interfaces:**
- Produces:
  - `print_event(e: dict) -> None`
  - `json_event(e: dict) -> None`
  - `class LoginRequired(RuntimeError)`
  - `run(api, *, probe, dry_run, only, include_unmapped, emit=print_event) -> int`
  - `PlaywrightAPI.ensure_login(headless=False, timeout_s=600, emit=print_event)`
  - `main(argv)` accepts `--json` and returns 0, 1 or 3.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_blackboard.py`)

```python
def test_run_emits_events_for_each_mode(inbox):
    ev = []
    bb.run(FakeAPI(), probe=True, dry_run=False, only=None, include_unmapped=False, emit=ev.append)
    assert [e["type"] for e in ev] == ["courses", "done"]
    assert ev[0]["probe"] is True and ev[1]["mode"] == "probe"
    assert any(c["folder"] == "Probability 2" for c in ev[0]["courses"])
    assert any(c["folder"] is None for c in ev[0]["courses"])  # an unmapped course is listed as skipped

    ev.clear()
    bb.run(FakeAPI(), probe=False, dry_run=True, only=None, include_unmapped=False, emit=ev.append)
    files = [e for e in ev if e["type"] == "file"]
    assert {e["action"] for e in files} == {"would_download"} and len(files) == 3
    assert next(e for e in ev if e["type"] == "course")["to_download"] == 3
    assert ev[-1] == {"type": "done", "mode": "preview", "files": 0, "bytes": 0}

    ev.clear()
    bb.run(FakeAPI(), probe=False, dry_run=False, only=None, include_unmapped=False, emit=ev.append)
    files = [e for e in ev if e["type"] == "file"]
    assert [e["action"] for e in files] == ["downloaded"] * 3 and all(e["kb"] >= 1 for e in files)
    assert ev[-1]["type"] == "done" and ev[-1]["mode"] == "sync" and ev[-1]["files"] == 3


def test_json_event_is_one_line_per_event(capsys):
    bb.json_event({"type": "file", "path": "Probabilité/é.pdf"})
    assert capsys.readouterr().out == '{"type": "file", "path": "Probabilité/é.pdf"}\n'


def test_headless_expired_session_exits_3(monkeypatch, capsys):
    class ExpiredAPI:
        def __init__(self, headless=False):
            self.headless = headless

        def ensure_login(self, headless=False, timeout_s=600, emit=None):
            raise bb.LoginRequired

        def close(self):
            pass

    monkeypatch.setattr(bb, "PlaywrightAPI", ExpiredAPI)
    assert bb.main(["--headless", "--json"]) == 3
    assert capsys.readouterr().out.strip() == '{"type": "login_required"}'
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_blackboard.py -q`
Expected: the 3 new tests FAIL (`run()` has no `emit`; there's no `json_event` or `LoginRequired`). The existing tests pass.

- [ ] **Step 3: Event printers**

Add to `app/sync/blackboard.py` after `write_atomic` (before `my_courses`):

```python
# --- events: what a run reports, printed as today's text or as JSON lines (--json) --------------

# 15-character labels keep the text output byte-for-byte what it was before events existed
LABEL = {
    "would_download": "would download ", "would_save_page": "would save page", "failed": "FAILED         ",
    "already_had": "already had    ", "downloaded": "downloaded     ", "saved_page": "saved page     ",
}


class LoginRequired(RuntimeError):
    """Headless run with an expired Blackboard session."""


def print_event(e: dict) -> None:
    t = e["type"]
    if t == "courses":
        print(f"\n{len(e['courses'])} courses on Blackboard:")
        for c in e["courses"]:
            print(f"  {'->' if c['folder'] else '  '} {c['name']:<45} {c['folder'] or '(skipped: no inbox folder)'}")
        if e["probe"]:
            print("\nProbe only: nothing downloaded. Fix wrong matches with blackboard_course_map in config.yaml.")
    elif t == "course":
        print(f"\n{e['folder']}: {e['files']} readable files, {e['to_download']} to download, {e['unchanged']} unchanged"
              + (f", {e['deleted_locally']} deleted locally (left alone)" if e["deleted_locally"] else ""))
        if e["skipped"]:
            print("  skipped, not readable yet: " + ", ".join(f"{n} {ext}" for ext, n in e["skipped"].items()))
    elif t == "file":
        a = e["action"]
        tail = (f": {e['error']}" if a == "failed"
                else f" ({e['kb']} KB)" if a in ("downloaded", "saved_page")
                else "  (a file with this name exists; kept if identical)" if e.get("adopt") else "")
        print(f"  {LABEL[a]} {e['path']}{tail}")
    elif t == "done":
        if e["mode"] == "sync":
            print(f"\nDone: {e['files']} files, {e['bytes'] / 1_048_576:.1f} MB. "
                  "The backend indexes them automatically if it's running.")
    elif t == "login_waiting":
        print("Log in to Blackboard in the browser window that just opened. Waiting…", flush=True)
    elif t == "logged_in":
        print("Logged in.", flush=True)
    elif t == "login_required":
        print("Blackboard session expired. Run once without --headless to log in.")
    elif t == "error":
        print(e["message"])


def json_event(e: dict) -> None:
    print(json.dumps(e, ensure_ascii=False), flush=True)
```

- [ ] **Step 4: `run()` emits instead of printing**

Change the signature to `def run(api: BlackboardAPI, *, probe: bool, dry_run: bool, only: str | None, include_unmapped: bool, emit=print_event) -> int:`. Replace its prints:

```python
    mode = "probe" if probe else "preview" if dry_run else "sync"
    emit({"type": "courses", "probe": probe,
          "courses": [{"name": clean_course_name(c["name"]), "folder": folder} for c, folder in mapping]})
    if probe:
        emit({"type": "done", "mode": mode, "files": 0, "bytes": 0})
        return 0
```

In the per-course loop:

```python
        emit({"type": "course", "folder": folder, "files": len(files), "to_download": len(plan.download),
              "unchanged": plan.unchanged, "deleted_locally": plan.deleted_locally,
              "skipped": dict(skipped.most_common())})
        for f, target, adopt in plan.download:
            rel = target.relative_to(inbox).as_posix()
            if dry_run:
                emit({"type": "file", "folder": folder, "path": rel, "adopt": adopt,
                      "action": "would_save_page" if f.text else "would_download"})
                continue
            try:
                ...unchanged download code...
            except Exception as e:  # keep going; the next run retries it
                emit({"type": "file", "folder": folder, "path": rel, "action": "failed", "error": str(e)})
                continue
            if adopt:
                if target.read_bytes() == data:
                    state[f.key] = {"path": rel, "modified": f.modified}
                    save_state(state)
                    emit({"type": "file", "folder": folder, "path": rel, "action": "already_had"})
                    continue
                ...unchanged...
            ...write_atomic, state, totals unchanged...
            emit({"type": "file", "folder": folder, "path": rel, "kb": max(1, len(data) // 1024),
                  "action": "saved_page" if f.text else "downloaded"})
    emit({"type": "done", "mode": mode, "files": total_new, "bytes": total_bytes})
    return 0
```

- [ ] **Step 5: Login and `main()`**

`ensure_login` gains `emit=print_event`. It raises `LoginRequired` instead of `SystemExit` when headless, emits `login_waiting` and `logged_in` instead of printing, and still raises `SystemExit("Timed out waiting for Blackboard login.")` on timeout.

`main()`:

```python
    ap.add_argument("--json", action="store_true", help="print one JSON event per line (used by the admin panel)")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # course names with accents on a cp1252 console
    emit = json_event if args.json else print_event
    try:
        api = PlaywrightAPI(headless=args.headless)
    except Exception as e:  # browser missing, profile locked by another run, ...
        emit({"type": "error", "message": f"Couldn't start the browser: {e}"})
        return 1
    try:
        api.ensure_login(headless=args.headless, emit=emit)
        return run(api, probe=args.probe, dry_run=args.dry_run, only=args.course,
                   include_unmapped=args.include_unmapped, emit=emit)
    except LoginRequired:
        emit({"type": "login_required"})
        return 3
    except SystemExit as e:
        emit({"type": "error", "message": str(e)})
        return 1
    finally:
        api.close()
```

- [ ] **Step 6: Run tests and lint**

Run: `uv run pytest -q && uv run ruff check --output-format concise app/sync tests/test_blackboard.py`
Expected: 66 passed (63 + 3). No new ruff findings (the one BLE001 on `except Exception` in `main` carries the comment; add `# noqa: BLE001` only if ruff flags it).

Also run it by hand: `uv run python -m app.sync.blackboard --help` shows `--json`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/sync/blackboard.py backend/tests/test_blackboard.py
git commit -m "Blackboard sync: report progress as events; --json prints them one per line"
```

---

### Task 2: Job runner, auto-sync, setting and API

**Files:**
- Create: `backend/app/admin/sync.py`
- Create: `backend/tests/fake_sync.py`, `backend/tests/test_sync_runner.py`
- Modify: `backend/app/config.py` (`sync_auto_days: int = 7`), `config.yaml` (document it)
- Modify: `backend/app/admin/settings.py` (the Blackboard group), `backend/tests/test_settings.py` (three groups)
- Modify: `backend/app/api/admin.py` (sync routes), `backend/app/api/routes.py` (`/health` flag), `backend/app/main.py` (start and stop `AutoSync`)

**Interfaces:**
- Consumes: the Task 1 CLI contract (`--json`, exit codes, events).
- Produces:
  - `sync.Busy`
  - `sync.SyncRunner(command=None, runs_file=..., state_file=..., clock=time.time)` with `.start(mode, course=None) -> dict`, `.cancel() -> dict | None`, `.wait(timeout=30)`, `.status() -> dict`, `.due(now=None) -> bool`, `.login_needed() -> bool`, `.last_full_sync() -> float | None`
  - `sync.runner` (module instance)
  - `sync.modules() -> list[str]`
  - `sync.AutoSync(first_delay=300, every=3600)` with `.start()` / `.stop()`
  - HTTP `GET /admin/sync`, `POST /admin/sync`, `POST /admin/sync/login`, `POST /admin/sync/cancel`, and `GET /health` gains `blackboard_login_needed`

- [ ] **Step 1: The fake script `tests/fake_sync.py`**

```python
"""Stand-in for app.sync.blackboard in the runner tests. FAKE_SYNC picks the behaviour: ok, slow, login, crash."""

import json
import os
import sys
import time

args = sys.argv[1:]
behaviour = os.environ.get("FAKE_SYNC", "ok")
dry = "--dry-run" in args


def out(e):
    print(json.dumps(e), flush=True)


print("args: " + " ".join(args), flush=True)  # not JSON: becomes a log event, and shows the flags used
out({"type": "courses", "probe": "--probe" in args, "courses": [
    {"name": "Probability 2", "folder": "Probability 2"}, {"name": "Engineering Internship", "folder": None}]})
if behaviour == "login":
    out({"type": "login_required"})
    sys.exit(3)
if behaviour == "slow":
    time.sleep(30)
out({"type": "file", "folder": "Probability 2", "path": "Probability 2/a.pdf", "kb": 12,
     "action": "would_download" if dry else "downloaded"})
out({"type": "file", "folder": "Probability 2", "path": "Probability 2/b.pdf", "action": "failed",
     "error": "download -> 500"})
if behaviour == "crash":
    out({"type": "error", "message": "boom"})
    sys.exit(1)
out({"type": "done", "mode": "preview" if dry else "sync", "files": 0 if dry else 1, "bytes": 0 if dry else 12288})
```

- [ ] **Step 2: Write the failing tests `tests/test_sync_runner.py`**

```python
import os
import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).parent / "fake_sync.py"
NOW = 1_800_000_000.0
DAY = 86_400


@pytest.fixture
def runner(tmp_path, monkeypatch):
    from app import config
    from app.admin.sync import SyncRunner

    (tmp_path / "inbox" / "Probability 2").mkdir(parents=True)
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("SYNC_AUTO_DAYS", "7")
    monkeypatch.delenv("FAKE_SYNC", raising=False)
    config.get_settings.cache_clear()
    clock = [NOW]
    r = SyncRunner(command=[sys.executable, str(FAKE)], runs_file=tmp_path / "runs.json",
                   state_file=tmp_path / "state.json", clock=lambda: clock[0])
    r.test_clock = clock
    yield r
    r.cancel()
    config.get_settings.cache_clear()


def logs(job):
    return " ".join(e["text"] for e in job["events"] if e["type"] == "log")


def test_run_collects_events_counts_and_history(runner):
    job = runner.start("sync")
    assert job["state"] == "running" and job["mode"] == "sync"
    runner.wait()
    s = runner.status()
    j = s["job"]
    assert j["state"] == "ok" and j["exit_code"] == 0
    assert j["counts"]["downloaded"] == 1 and j["counts"]["failed"] == 1 and j["bytes"] == 12288
    assert j["courses"][1] == {"name": "Engineering Internship", "folder": None}
    assert "--json --headless" in logs(j) and "--dry-run" not in logs(j)
    assert s["runs"][0]["state"] == "ok" and "events" not in s["runs"][0]
    assert s["modules"] == ["Probability 2"]


def test_modes_pass_the_right_flags(runner):
    runner.start("preview", course="Probability 2")
    runner.wait()
    j = runner.status()["job"]
    assert "--headless --dry-run --course Probability 2" in logs(j) and j["counts"]["would_download"] == 1
    runner.start("login")
    runner.wait()
    assert "--headless" not in logs(runner.status()["job"])  # login opens a visible window


def test_busy_and_cancel(runner, monkeypatch):
    from app.admin.sync import Busy

    monkeypatch.setenv("FAKE_SYNC", "slow")
    runner.start("sync")
    with pytest.raises(Busy):
        runner.start("preview")
    assert runner.cancel()["state"] == "cancelled"
    assert runner.status()["runs"][0]["state"] == "cancelled"
    assert runner.cancel() is None  # nothing running


def test_login_required_sets_flag_and_ok_clears_it(runner, monkeypatch):
    monkeypatch.setenv("FAKE_SYNC", "login")
    runner.start("sync")
    runner.wait()
    s = runner.status()
    assert s["job"]["state"] == "login_required" and s["login_needed"] is True
    assert runner.due() is False and s["next_auto"] is None

    monkeypatch.setenv("FAKE_SYNC", "ok")
    runner.start("login")
    runner.wait()
    assert runner.login_needed() is False


def test_crash_is_failed_with_message(runner, monkeypatch):
    monkeypatch.setenv("FAKE_SYNC", "crash")
    runner.start("sync")
    runner.wait()
    j = runner.status()["job"]
    assert j["state"] == "failed" and j["error"] == "boom"


def test_due_follows_last_sync_setting_and_state_file(runner, monkeypatch):
    from app import config

    assert runner.due() is True  # never synced
    runner.state_file.write_text("{}", encoding="utf-8")  # the command-line sync ran two days ago
    os.utime(runner.state_file, (NOW - 2 * DAY, NOW - 2 * DAY))
    assert runner.due() is False
    assert runner.status()["next_auto"] is not None
    os.utime(runner.state_file, (NOW - 8 * DAY, NOW - 8 * DAY))
    assert runner.due() is True
    monkeypatch.setenv("SYNC_AUTO_DAYS", "0")
    config.get_settings.cache_clear()
    assert runner.due() is False and runner.status()["next_auto"] is None


def test_routes(runner, monkeypatch):
    from fastapi.testclient import TestClient

    from app.admin import sync
    from app.llm import ollama
    from app.main import create_app

    monkeypatch.setattr(sync, "runner", runner)
    monkeypatch.setattr(ollama, "status", lambda: {"reachable": False})
    client = TestClient(create_app())
    assert client.post("/admin/sync", json={"mode": "preview", "course": "Nope"}).status_code == 400
    assert client.post("/admin/sync", json={"mode": "bogus"}).status_code == 422
    assert client.post("/admin/sync/cancel").status_code == 404
    r = client.post("/admin/sync", json={"mode": "probe"})
    assert r.status_code == 202 and r.json()["mode"] == "probe"
    runner.wait()
    assert client.get("/admin/sync").json()["job"]["courses"][0]["folder"] == "Probability 2"
    assert client.get("/health").json()["blackboard_login_needed"] is False
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_sync_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.admin.sync'`.

- [ ] **Step 4: The setting**

`app/config.py`: add `sync_auto_days: int = 7  # days between automatic syncs from the backend; 0 turns them off` under the Blackboard settings.

`config.yaml`, in the Blackboard block:

```yaml
sync_auto_days: 7        # the backend syncs on its own this often (days); 0 = never. Also editable in /admin
```

`app/admin/settings.py`: append to `EDITABLE`:

```python
    Field("sync_auto_days", "Blackboard", "Automatic sync every", "int",
          "Days between automatic syncs; 0 turns them off", 0, 30),
```

`tests/test_settings.py`: in `test_routes`, change the group assertion to `["Retrieval", "Answers", "Blackboard"]`. Add `"sync_auto_days"` to `KEYS`.

- [ ] **Step 5: `app/admin/sync.py`**

```python
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
        v = {k: v for k, v in job.items() if k != "cancelled"}
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
            except Exception:
                log.exception("auto-sync check failed")
            if self._stop.wait(self.every):
                return
```

- [ ] **Step 6: Routes, health and lifespan**

`app/api/admin.py`: add `from ..admin import sync as sync_jobs` and:

```python
class SyncBody(BaseModel):
    mode: Literal["sync", "preview", "probe"]
    course: str | None = None


@router.get("/sync")
def sync_status() -> dict:
    return sync_jobs.runner.status()


@router.post("/sync", status_code=202)
def sync_start(body: SyncBody) -> dict:
    if body.course is not None and body.course not in sync_jobs.modules():
        raise HTTPException(400, "no such module folder in the inbox")
    try:
        return sync_jobs.runner.start(body.mode, body.course)
    except sync_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sync/login", status_code=202)
def sync_login() -> dict:
    try:
        return sync_jobs.runner.start("login")
    except sync_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sync/cancel")
def sync_cancel() -> dict:
    job = sync_jobs.runner.cancel()
    if job is None:
        raise HTTPException(404, "no sync is running")
    return job
```

`app/api/routes.py` `/health`: add `from ..admin import sync as sync_jobs`, and put `"blackboard_login_needed": sync_jobs.runner.login_needed()` in the returned dict.

`app/main.py` lifespan: after `watcher.start()`, add `autosync = AutoSync(); autosync.start()`. Before `watcher.stop()`, add `autosync.stop(); runner.cancel()`, so a running sync doesn't outlive the backend. Import both with `from .admin.sync import AutoSync, runner`.

- [ ] **Step 7: Run all tests and lint**

Run: `uv run pytest -q && uv run ruff check --output-format concise app/admin app/api app/main.py tests/test_sync_runner.py tests/fake_sync.py tests/test_settings.py`
Expected: 73 passed (66 + 7); no new findings (add `# noqa: BLE001` with a reason on the `AutoSync` catch-all if flagged).

- [ ] **Step 8: Commit**

```bash
git add config.yaml backend/app/config.py backend/app/admin/sync.py backend/app/admin/settings.py backend/app/api/admin.py backend/app/api/routes.py backend/app/main.py backend/tests/fake_sync.py backend/tests/test_sync_runner.py backend/tests/test_settings.py
git commit -m "Admin sync: run the Blackboard sync as a job with history, cancel, login and weekly auto-sync"
```

---

### Task 3: Sync section and rail notice

**Files:**
- Modify: `frontend/lib/api.ts` (`SyncJob`, `SyncStatus`, `Health.blackboard_login_needed`)
- Create: `frontend/components/admin/SyncCard.tsx`
- Modify: `frontend/app/admin/page.tsx`, `frontend/components/Rail.tsx`, `frontend/app/globals.css`

**Interfaces:**
- Consumes: the Task 2 routes, `getJSON`/`postJSON`/`ApiError`, `ago` (`lib/seen.ts`).
- Produces: `<SyncCard />` with `id="sync"` for the rail link `/admin#sync`.

- [ ] **Step 1: Types (`lib/api.ts`)**

Add `blackboard_login_needed?: boolean;` to `Health`, and:

```ts
export type SyncEvent = { type: string; [k: string]: unknown };
export type SyncAction = "downloaded" | "saved_page" | "already_had" | "would_download" | "would_save_page" | "failed";
export type SyncJob = {
  id: number;
  mode: "sync" | "preview" | "probe" | "login";
  course: string | null;
  started_at: string;
  finished_at: string | null;
  state: "running" | "ok" | "login_required" | "failed" | "cancelled";
  exit_code: number | null;
  counts: Record<SyncAction, number>;
  bytes: number;
  error: string | null;
  events?: SyncEvent[];
  courses?: { name: string; folder: string | null }[] | null;
};
export type SyncStatus = {
  job: SyncJob | null;
  runs: SyncJob[];
  login_needed: boolean;
  last_full_sync: string | null;
  next_auto: string | null;
  auto_days: number;
  modules: string[];
};
```

- [ ] **Step 2: `components/admin/SyncCard.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, type SyncAction, type SyncJob, type SyncStatus } from "@/lib/api";
import { ago } from "@/lib/seen";

const POLL_MS = 1500;
const ACTION: Record<SyncAction, string> = {
  downloaded: "Downloaded",
  saved_page: "Saved page",
  already_had: "Already had",
  would_download: "Would download",
  would_save_page: "Would save page",
  failed: "Failed",
};
const MODE: Record<SyncJob["mode"], string> = {
  sync: "Sync",
  preview: "Preview",
  probe: "Course mapping",
  login: "Log in",
};
const mb = (b: number) => `${(b / 1_048_576).toFixed(1)} MB`;

function until(iso: string): string {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  return days <= 0 ? "at the next hourly check" : `in ${days} day${days === 1 ? "" : "s"}`;
}

function outcome(j: SyncJob): string {
  const c = j.counts;
  if (j.state === "running") return `${MODE[j.mode]} running…`;
  if (j.state === "cancelled") return "Cancelled.";
  if (j.state === "login_required") return "Your Blackboard session expired: log in, then sync again.";
  if (j.state === "failed") return `Failed: ${j.error ?? `the sync exited with code ${j.exit_code}`}`;
  if (j.mode === "probe") return "Course mapping below.";
  if (j.mode === "login") return "Logged in. The session is saved for the next syncs.";
  if (j.mode === "preview") {
    const n = c.would_download + c.would_save_page;
    return n ? `Preview: ${n} file${n === 1 ? "" : "s"} would be downloaded.` : "Preview: everything is up to date.";
  }
  const n = c.downloaded + c.saved_page;
  return `Done: ${n} file${n === 1 ? "" : "s"}, ${mb(j.bytes)}${c.failed ? `, ${c.failed} failed (retried next time)` : ""}.`;
}

/** Blackboard sync: run it, watch it, and see when it last ran and runs next. */
export function SyncCard() {
  const [s, setS] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [course, setCourse] = useState("");

  const load = useCallback(() => {
    getJSON<SyncStatus>("/admin/sync")
      .then((v) => {
        setS(v);
        setError(null);
      })
      .catch(() => setError("Couldn't reach the backend."));
  }, []);
  useEffect(load, [load]);

  const running = s?.job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [running, load]);

  async function post(path: string, body: unknown) {
    setError(null);
    try {
      await postJSON(path, body);
    } catch (e) {
      setError((e as Error).message);
    }
    load();
  }

  if (!s) return <p className="muted">{error ?? "Checking the sync…"}</p>;
  const job = s.job;
  const files = (job?.events ?? []).filter((e) => e.type === "file");
  const byFolder = new Map<string, typeof files>();
  for (const e of files.toReversed()) {
    const f = String(e.folder);
    byFolder.set(f, [...(byFolder.get(f) ?? []), e]);
  }
  const lastFull = s.runs.find((r) => r.mode === "sync" && !r.course && r.state === "ok");

  return (
    <section className="admin-card" id="sync" aria-labelledby="sync-h">
      <header className="admin-card-head">
        <h2 id="sync-h">Blackboard sync</h2>
        {running && (
          <button type="button" className="quiet-btn" onClick={() => post("/admin/sync/cancel", {})}>
            Cancel
          </button>
        )}
      </header>

      <p className="muted">
        {s.last_full_sync ? `Last full sync ${ago(s.last_full_sync)}` : "Never synced from here"}
        {lastFull ? ` · ${lastFull.counts.downloaded + lastFull.counts.saved_page} files` : ""} ·{" "}
        {s.auto_days === 0
          ? "Automatic sync off"
          : s.next_auto
            ? `Next automatic sync ${until(s.next_auto)}`
            : "Automatic sync paused"}
      </p>

      {s.login_needed && (
        <p className="notice sync-login">
          Your Blackboard session expired. Log in to sync again: an Edge window opens for you to sign in, and the
          session is saved.{" "}
          <button type="button" className="quiet-btn" disabled={running} onClick={() => post("/admin/sync/login", {})}>
            Log in
          </button>
        </p>
      )}

      <div className="sync-actions">
        <button type="button" className="quiet-btn" disabled={running} onClick={() => post("/admin/sync", { mode: "sync" })}>
          Sync now
        </button>
        <button type="button" className="quiet-btn" disabled={running} onClick={() => post("/admin/sync", { mode: "preview" })}>
          Preview
        </button>
        <button type="button" className="quiet-btn" disabled={running} onClick={() => post("/admin/sync", { mode: "probe" })}>
          Course mapping
        </button>
        <span className="sync-one">
          <label className="sr-only" htmlFor="sync-course">
            Module
          </label>
          <select id="sync-course" value={course} onChange={(e) => setCourse(e.target.value)} disabled={running}>
            <option value="">Choose a module…</option>
            {s.modules.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="quiet-btn"
            disabled={running || !course}
            onClick={() => post("/admin/sync", { mode: "sync", course })}
          >
            Sync this module
          </button>
        </span>
      </div>
      {error && <p className="action-note bad">{error}</p>}

      {job && (
        <div className="sync-job" aria-live="polite">
          <p className={job.state === "failed" || job.state === "login_required" ? "bad" : ""}>
            <strong>
              {MODE[job.mode]}
              {job.course ? ` · ${job.course}` : ""}
            </strong>{" "}
            {outcome(job)}
          </p>
          {files.length > 0 && (
            <div className="sync-log">
              {[...byFolder].map(([folder, evs]) => (
                <section key={folder}>
                  <h3>{folder}</h3>
                  <ul>
                    {evs.map((e, i) => (
                      <li key={`${e.path}-${i}`} className={e.action === "failed" ? "bad" : ""}>
                        <span className="sync-action">{ACTION[e.action as SyncAction]}</span>
                        <span className="callno">{String(e.path).split("/").slice(1).join("/")}</span>
                        {e.action === "failed" && <span> {String(e.error)}</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
          {job.mode === "probe" && job.courses && (
            <table className="admin-table">
              <thead>
                <tr>
                  <th scope="col">Blackboard course</th>
                  <th scope="col">Inbox folder</th>
                </tr>
              </thead>
              <tbody>
                {job.courses.map((c) => (
                  <tr key={c.name} className={c.folder ? "" : "muted"}>
                    <th scope="row">{c.name}</th>
                    <td>{c.folder ?? "skipped: no inbox folder"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {job.mode === "probe" && job.courses && (
            <p className="muted">Fix wrong matches with blackboard_course_map in config.yaml.</p>
          )}
        </div>
      )}

      {s.runs.length > 0 && (
        <details className="sync-runs">
          <summary>Recent runs</summary>
          <ul className="admin-list">
            {s.runs.map((r) => (
              <li key={r.id}>
                <span className="admin-item">
                  <strong>
                    {MODE[r.mode]}
                    {r.course ? ` · ${r.course}` : ""}
                  </strong>
                  <span className="muted">
                    {ago(r.started_at)} · {outcome(r)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
```

`files.toReversed()` needs ES2023 lib. If `tsc` complains, use `[...files].reverse()`.

- [ ] **Step 3: Page, rail, CSS**

`app/admin/page.tsx`: import `SyncCard` and render it between `<LibraryAdmin />` and `<SettingsCard />`.

`components/Rail.tsx`, in the footer after the health link:

```tsx
        {health && health !== "down" && health.blackboard_login_needed && (
          <Link href="/admin#sync" className="bb-login">
            Blackboard: log in needed
          </Link>
        )}
```

Append to `app/globals.css`:

```css
/* ---- admin sync ---------------------------------------------------------------------------- */
.sync-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin: 0.6rem 0;
}

.sync-one {
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
}

.sync-one select {
  font: inherit;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--rule-blue);
  border-radius: 4px;
  background: var(--card);
  color: var(--ink);
}

.sync-login {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
}

.sync-job .bad,
.sync-log .bad {
  color: var(--bad);
}

.sync-log {
  max-height: 22rem;
  overflow: auto;
  border-top: 1px solid var(--rule-blue);
  margin-top: 0.5rem;
}

.sync-log h3 {
  margin: 0.7rem 0 0.2rem;
}

.sync-log ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.sync-log li {
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
  padding: 0.2rem 0;
  font-size: 0.86rem;
}

.sync-action {
  flex: none;
  width: 8.5rem;
  color: var(--muted);
}

.sync-log .callno {
  overflow-wrap: anywhere;
  white-space: normal;
}

.sync-runs {
  margin-top: 0.8rem;
}

.sync-runs summary {
  cursor: pointer;
  color: var(--primary);
}

.bb-login {
  display: block;
  margin-top: 0.3rem;
  color: #ffb4ab; /* the rail's own "bad" ink, as .health .bad */
  text-decoration: none;
}

.bb-login:hover {
  text-decoration: underline;
}

@media (max-width: 860px) {
  .sync-action {
    width: 6.5rem;
  }
}
```

- [ ] **Step 4: Typecheck, lint, commit**

Run: `npx tsc --noEmit && npm run lint`. Expected: clean.

```bash
git add frontend/lib/api.ts frontend/components/admin/SyncCard.tsx frontend/app/admin/page.tsx frontend/components/Rail.tsx frontend/app/globals.css
git commit -m "Admin page: Blackboard sync section with live progress, course mapping and run history"
```

---

### Task 4: Verify in the browser and polish

- [ ] **Step 1:** Restart the backend, so the new routes, the setting and the `AutoSync` thread load. Check the log shows no auto-sync starting within the first 5 minutes.
- [ ] **Step 2: Ask the user before touching Blackboard.** With their go-ahead, run these from the panel against the real session:
  - **Course mapping:** the table matches today's `--probe` output.
  - **Preview:** a count, and nothing written under `inbox/`.
  - **Sync this module** on the smallest module.

  If the session has expired, `login_needed` appears in the panel and the rail. **Leave Log in and a full Sync now to the user.**
- [ ] **Step 3: Cancel.** Start a Preview and cancel it at once. The run history shows it as cancelled, and no `python -m app.sync.blackboard` process is left running (`Get-Process python` / check by command line).
- [ ] **Step 4: Settings.** The new "Automatic sync every" row appears under Settings · Blackboard. Setting it to 0 shows "Automatic sync off" in the Sync header. Set it back afterwards with Reset.
- [ ] **Step 5:** Console is clear of errors. Mobile width has no horizontal scroll, the action buttons wrap, and the progress list is readable.
- [ ] **Step 6: Impeccable polish pass** against `DESIGN.md`: one batched inspection round (desktop + mobile), one fix batch, then stop.
- [ ] **Step 7:** Run `cd backend && uv run pytest -q` (73 passed) and `cd frontend && npx tsc --noEmit && npm run lint`, then commit any polish.
