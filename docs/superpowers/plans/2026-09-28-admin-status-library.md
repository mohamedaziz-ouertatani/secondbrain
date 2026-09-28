# Admin Panel Part 1 (Status + Library) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An `/admin` page showing system status (services, LLM GPU share, VRAM, latency, index size) and library management (per-module counts, problem files, forced re-index, exclude/include), plus a watcher that handles folder deletes and renames.

**Architecture:** The pipeline gains `force`, exclusion (a new `excluded_paths` table), `reindex` and `remove_folder`. The watcher stops ignoring directory events. A new `app/admin/status.py` assembles status from independent, fail-soft parts, and a new `app/api/admin.py` router exposes status and library actions. The frontend adds `/admin` with a Status card and a Library section, reached from the rail footer.

**Tech Stack:** FastAPI, psycopg 3, watchdog, pytest (a throwaway Postgres DB), Next.js 16 client components, plain CSS.

**Spec:** `docs/superpowers/specs/2026-09-28-admin-status-library-design.md`

## Global Constraints

- Postgres on 5433. Backend commands run from `backend/` with `uv run`; frontend commands run from `frontend/`.
- Paths in the API are inbox-relative POSIX strings, the same form as `documents.path`. Anything resolving outside the inbox gets 400.
- Every index write stays behind `pipeline._lock`. Rescan and re-index share one 409 guard.
- Status parts fail independently: a failing part is `null`, or `{"available": false}` for `gpu`. `/admin/status` never returns 500 because of one part.
- `nvidia-smi` is called with a 3 s timeout. Status polling runs every 10 s, only while the tab is visible.
- There's no frontend unit-test runner. Checks are `npx tsc --noEmit`, `npm run lint`, then the browser pane.
- UI follows `DESIGN.md` (card catalogue): no coloured side stripes, and tints only to mean "filed in this unit".

---

### Task 1: Pipeline: exclusion, forced re-index, folder removal

**Files:**
- Create: `backend/app/migrations/004_excluded_paths.sql`
- Modify: `backend/app/ingest/pipeline.py`
- Create: `backend/tests/fakes.py`
- Modify: `backend/tests/test_pipeline.py` (import the fakes instead of defining them)
- Test: `backend/tests/test_admin_pipeline.py`

**Interfaces:**
- Produces:
  - `ingest_file(path: Path, embedder: Embedder | None = None, counter: TokenCounter | None = None, force: bool = False) -> str`, which now can also return `"excluded"`
  - `is_excluded(rel: str) -> bool`
  - `exclude(rel: str) -> bool`
  - `include(rel: str, embedder=None, counter=None) -> str | None` (`None` means the path wasn't excluded; `"missing"` means it isn't on disk)
  - `reindex(rel: str | None = None, course: str | None = None, embedder=None, counter=None) -> dict[str, int]`
  - `remove_folder(path: Path) -> int`
  - `rescan()` stats gain an `"excluded"` count.

- [ ] **Step 1: Shared test fakes**

`backend/tests/fakes.py`:

```python
"""Stand-ins for Ollama and the bge-m3 tokenizer, so DB tests run offline and fast."""

import numpy as np


def words(s: str) -> int:
    return len(s.split())


def fake_embed(texts):
    rng = [np.random.default_rng(abs(hash(t)) % 2**32) for t in texts]
    return [(v := r.standard_normal(1024).astype(np.float32)) / np.linalg.norm(v) for r in rng]
```

In `tests/test_pipeline.py`, delete the `_words` and `fake_embed` definitions and the `numpy` import, and add `from fakes import fake_embed` and `from fakes import words as _words`. (pytest prepends the test directory to `sys.path`, so `import fakes` works.)

Run: `uv run pytest -q`. Expected: 46 passed.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_admin_pipeline.py`:

```python
from fakes import fake_embed, words


def note(inbox, rel, body="Paragraph about gaussian vectors and their characteristic function. " * 20):
    p = inbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def paths(db):
    with db.get_pool().connection() as conn:
        return sorted(r["path"] for r in conn.execute("SELECT path FROM documents"))


def test_exclude_include_and_rescan(env):
    from app.ingest.pipeline import exclude, include, ingest_file, rescan

    inbox, db = env
    a = note(inbox, "Prob/a.md")
    note(inbox, "Prob/b.md")
    assert rescan(fake_embed, words)["ok"] == 2

    assert exclude("Prob/a.md") is True
    assert paths(db) == ["Prob/b.md"]
    assert exclude("Prob/a.md") is False  # idempotent, nothing left to remove
    assert ingest_file(a, fake_embed, words) == "excluded"
    stats = rescan(fake_embed, words)
    assert stats["excluded"] == 1 and stats["removed"] == 0
    assert paths(db) == ["Prob/b.md"]

    assert include("Prob/a.md", fake_embed, words) == "ok"
    assert paths(db) == ["Prob/a.md", "Prob/b.md"]
    assert include("Prob/a.md", fake_embed, words) is None  # no longer excluded


def test_rescan_drops_stale_row_of_excluded_file(env):
    from app.ingest.pipeline import rescan

    inbox, db = env
    note(inbox, "Prob/a.md")
    rescan(fake_embed, words)
    with db.get_pool().connection() as conn:  # excluded behind the pipeline's back
        conn.execute("INSERT INTO excluded_paths (path) VALUES ('Prob/a.md')")
    assert rescan(fake_embed, words)["removed"] == 1
    assert paths(db) == []


def test_include_missing_file(env):
    from app.ingest.pipeline import exclude, include

    inbox, db = env
    exclude("Gone/x.md")
    assert include("Gone/x.md", fake_embed, words) == "missing"


def test_forced_reindex_of_unchanged_file_and_course(env):
    from app.ingest.pipeline import ingest_file, reindex

    inbox, db = env
    a = note(inbox, "Prob/a.md")
    note(inbox, "Prob/b.md")
    note(inbox, "Algo/c.md")
    for p in inbox.rglob("*.md"):
        ingest_file(p, fake_embed, words)
    assert ingest_file(a, fake_embed, words) == "skipped"
    assert ingest_file(a, fake_embed, words, force=True) == "ok"

    calls = []

    def counting_embed(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    assert reindex(course="Prob", embedder=counting_embed, counter=words) == {"ok": 2}
    assert len(calls) == 2  # Algo untouched
    assert reindex(rel="Algo/c.md", embedder=fake_embed, counter=words) == {"ok": 1}


def test_remove_folder_only_drops_that_prefix(env):
    from app.ingest.pipeline import remove_folder, rescan

    inbox, db = env
    note(inbox, "Prob/a.md")
    note(inbox, "Prob/sub/b.md")
    note(inbox, "Prob 2/c.md")  # shares the "Prob" prefix but is another folder
    rescan(fake_embed, words)
    assert remove_folder(inbox / "Prob") == 2
    assert paths(db) == ["Prob 2/c.md"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_admin_pipeline.py -q`
Expected: FAIL with `ImportError: cannot import name 'exclude'`.

- [ ] **Step 4: Migration**

`backend/app/migrations/004_excluded_paths.sql`:

```sql
-- Files kept on disk but left out of the index (admin "Exclude"). Same path form as documents.path.
CREATE TABLE excluded_paths (
    path        TEXT PRIMARY KEY,
    excluded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 5: Pipeline changes (`app/ingest/pipeline.py`)**

Change the `ingest_file` signature and its opening:

```python
def ingest_file(
    path: Path, embedder: Embedder | None = None, counter: TokenCounter | None = None, force: bool = False
) -> str:
    """Ingest or re-ingest one file. Returns 'skipped' | 'excluded' | 'ok' | 'empty_text' | 'error'.

    force re-ingests even when the file and parser are unchanged (admin "Re-index").
    """
    s = get_settings()
    rel = rel_path(path)
    embedder = embedder or ollama.embed  # looked up per call so tests can swap it
    with _lock:
        if is_excluded(rel):
            return "excluded"
        digest = sha256_of(path)
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT sha256, status, parser_version FROM documents WHERE path = %s", (rel,)
            ).fetchone()
        if (not force and row and row["sha256"] == digest and row["status"] != "error"
                and row["parser_version"] == PARSER_VERSION):
            return "skipped"
```

(The rest of the function is unchanged.) Change `rescan`'s signature to `embedder: Embedder | None = None` and its loop to:

```python
    for p in sorted(inbox.rglob("*")):
        if p.is_file() and is_supported(p):
            result = ingest_file(p, embedder, counter)
            if result != "excluded":  # an excluded file counts as gone, so a stale row is dropped
                seen.add(rel_path(p))
            stats[result] = stats.get(result, 0) + 1
```

Add after `remove_file`:

```python
def is_excluded(rel: str) -> bool:
    with get_pool().connection() as conn:
        return conn.execute("SELECT 1 FROM excluded_paths WHERE path = %s", (rel,)).fetchone() is not None


def exclude(rel: str) -> bool:
    """Leave the file on disk but take it out of the index for good. True if a document was removed."""
    with _lock, get_pool().connection() as conn, conn.transaction():
        conn.execute("INSERT INTO excluded_paths (path) VALUES (%s) ON CONFLICT DO NOTHING", (rel,))
        removed = conn.execute("DELETE FROM documents WHERE path = %s", (rel,)).rowcount > 0
    log.info("excluded %s", rel)
    return removed


def include(rel: str, embedder: Embedder | None = None, counter: TokenCounter | None = None) -> str | None:
    """Undo exclude and ingest the file again. None if it wasn't excluded, 'missing' if it's not on disk."""
    with _lock, get_pool().connection() as conn:
        if conn.execute("DELETE FROM excluded_paths WHERE path = %s", (rel,)).rowcount == 0:
            return None
    path = get_settings().inbox / rel
    if not (path.is_file() and is_supported(path)):
        return "missing"
    return ingest_file(path, embedder, counter)


def reindex(
    rel: str | None = None, course: str | None = None,
    embedder: Embedder | None = None, counter: TokenCounter | None = None,
) -> dict[str, int]:
    """Re-parse and re-embed one file or every file of one module, even if unchanged."""
    inbox = get_settings().inbox
    files = [inbox / rel] if rel else sorted(p for p in (inbox / course).rglob("*") if p.is_file() and is_supported(p))
    stats: dict[str, int] = {}
    for p in files:
        result = ingest_file(p, embedder, counter, force=True)
        stats[result] = stats.get(result, 0) + 1
    return stats


def remove_folder(path: Path) -> int:
    """A module folder was deleted or renamed: drop every document under it."""
    prefix = rel_path(path) + "/"
    with _lock, get_pool().connection() as conn:
        n = conn.execute("DELETE FROM documents WHERE starts_with(path, %s)", (prefix,)).rowcount
    if n:
        log.info("removed folder %s (%d documents)", prefix, n)
    return n
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q`
Expected: 51 passed (46 + 5).

- [ ] **Step 7: Commit**

```bash
git add backend/app/migrations/004_excluded_paths.sql backend/app/ingest/pipeline.py backend/tests/fakes.py backend/tests/test_pipeline.py backend/tests/test_admin_pipeline.py
git commit -m "Pipeline: exclude/include files, forced re-index, folder removal"
```

---

### Task 2: Watcher handles folder deletes, renames and pastes

**Files:**
- Modify: `backend/app/ingest/watcher.py`
- Test: `backend/tests/test_watcher.py`

**Interfaces:**
- Consumes: `remove_folder`, `ingest_file` (Task 1).
- Produces: `InboxWatcher.folder_gone(path: Path) -> None`, `InboxWatcher.touch_tree(path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_watcher.py`:

```python
from watchdog.events import DirCreatedEvent, DirDeletedEvent, DirMovedEvent

from fakes import fake_embed, words


def drain(w):
    for path, retries in w._due():
        w._process(path, retries)


def paths(db):
    with db.get_pool().connection() as conn:
        return sorted(r["path"] for r in conn.execute("SELECT path FROM documents"))


def test_folder_delete_rename_and_paste(env, monkeypatch):
    from app.ingest import pipeline, watcher
    from app.ingest.pipeline import rescan

    inbox, db = env
    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    monkeypatch.setattr(watcher, "DEBOUNCE_S", 0)
    for rel in ("Old/a.md", "Old/sub/b.md", "Keep/c.md"):
        p = inbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("Some text about brownian motion increments. " * 10, encoding="utf-8")
    rescan(fake_embed, words)

    w = watcher.InboxWatcher()  # not started: no real filesystem watching
    handler = watcher._Handler(w)

    # rename Old -> New: old paths leave, files are re-ingested under the new module
    (inbox / "Old").rename(inbox / "New")
    handler.on_any_event(DirMovedEvent(str(inbox / "Old"), str(inbox / "New")))
    drain(w)
    assert paths(db) == ["Keep/c.md", "New/a.md", "New/sub/b.md"]

    # delete a whole module folder
    for f in sorted((inbox / "New").rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    (inbox / "New").rmdir()
    handler.on_any_event(DirDeletedEvent(str(inbox / "New")))
    assert paths(db) == ["Keep/c.md"]

    # a folder pasted in one go
    (inbox / "Pasted").mkdir()
    (inbox / "Pasted" / "d.md").write_text("Pasted note about stochastic processes. " * 10, encoding="utf-8")
    handler.on_any_event(DirCreatedEvent(str(inbox / "Pasted")))
    drain(w)
    assert paths(db) == ["Keep/c.md", "Pasted/d.md"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_watcher.py -q`
Expected: FAIL: after the rename, `paths(db)` still lists `Old/...` (directory events are ignored).

- [ ] **Step 3: Implement (`app/ingest/watcher.py`)**

Change the import to `from .pipeline import ingest_file, is_supported, remove_file, remove_folder, rescan`. Replace `_Handler.on_any_event`:

```python
    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            # A module folder deleted, renamed or pasted in can arrive as one directory event (Windows).
            if event.event_type in ("deleted", "moved"):
                self.w.folder_gone(Path(event.src_path))
            if event.event_type == "moved":
                self.w.touch_tree(Path(event.dest_path))
            elif event.event_type == "created":
                self.w.touch_tree(Path(event.src_path))
            return
        # The worker decides ingest vs. remove by whether the path still exists.
        if event.event_type in ("created", "modified", "closed", "deleted", "moved"):
            self.w.touch(Path(event.src_path))
        if event.event_type == "moved":
            self.w.touch(Path(event.dest_path))
```

Add to `InboxWatcher` after `touch`:

```python
    def touch_tree(self, folder: Path) -> None:
        for p in folder.rglob("*"):
            if p.is_file():
                self.touch(p)

    def folder_gone(self, folder: Path) -> None:
        try:
            remove_folder(folder)
        except Exception:
            log.exception("failed to drop folder %s", folder)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: 52 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/watcher.py backend/tests/test_watcher.py
git commit -m "Watcher: drop and re-ingest documents when a module folder is deleted, renamed or pasted"
```

---

### Task 3: Status and library API

**Files:**
- Create: `backend/app/admin/__init__.py` (empty), `backend/app/admin/status.py`
- Modify: `backend/app/llm/ollama.py` (add `loaded()`)
- Create: `backend/app/api/jobs.py` (the shared rescan/re-index guard)
- Create: `backend/app/api/admin.py`
- Modify: `backend/app/api/routes.py` (use the shared guard), `backend/app/main.py` (include the admin router)
- Test: `backend/tests/test_admin_api.py`

**Interfaces:**
- Consumes: Task 1 pipeline functions.
- Produces:
  - `GET /admin/status` returning `AdminStatus` (shape in the spec)
  - `GET /admin/library` returning `{modules, problems, excluded}`
  - `POST /admin/reindex` `{path}|{course}` returning a status-count dict
  - `POST /admin/exclude` `{path}` returning `{removed: bool}`
  - `POST /admin/include` `{path}` returning `{status: str}`
  - `ollama.loaded() -> list[dict] | None`
  - `jobs.exclusive()`: a context manager that raises `HTTPException(409)` while another index job runs.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_admin_api.py`:

```python
import subprocess

import pytest

from fakes import fake_embed, words


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.ingest import pipeline
    from app.main import create_app

    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    return TestClient(create_app())  # no `with`: no watcher


def write(inbox, rel, body="Text about gaussian vectors and their characteristic functions. " * 10):
    p = inbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_library_exclude_include_reindex(env, client):
    from app.ingest.pipeline import rescan

    inbox, db = env
    write(inbox, "Prob/a.md")
    write(inbox, "Prob/b.md")
    (inbox / "Prob" / "scan.txt").write_text("", encoding="utf-8")  # no text: a problem file
    rescan(fake_embed, words)

    lib = client.get("/admin/library").json()
    assert lib["modules"] == [{"course": "Prob", "documents": 3, "chunks": lib["modules"][0]["chunks"], "problems": 1}]
    assert [p["path"] for p in lib["problems"]] == ["Prob/scan.txt"]

    assert client.post("/admin/exclude", json={"path": "Prob/a.md"}).json() == {"removed": True}
    lib = client.get("/admin/library").json()
    assert lib["modules"][0]["documents"] == 2
    assert [(e["path"], e["on_disk"]) for e in lib["excluded"]] == [("Prob/a.md", True)]

    assert client.post("/admin/include", json={"path": "Prob/a.md"}).json() == {"status": "ok"}
    assert client.post("/admin/include", json={"path": "Prob/a.md"}).status_code == 404

    assert client.post("/admin/reindex", json={"course": "Prob"}).json() == {"ok": 2, "empty_text": 1}
    assert client.post("/admin/reindex", json={"path": "Prob/b.md"}).json() == {"ok": 1}
    assert client.post("/admin/reindex", json={}).status_code == 400
    assert client.post("/admin/reindex", json={"path": "Prob/b.md", "course": "Prob"}).status_code == 400
    assert client.post("/admin/reindex", json={"path": "Prob/nope.md"}).status_code == 404
    assert client.post("/admin/reindex", json={"course": "Nope"}).status_code == 404
    assert client.post("/admin/exclude", json={"path": "../outside.md"}).status_code == 400


def test_status_parts(env, client, monkeypatch):
    from app.admin import status
    from app.llm import ollama

    _, db = env
    monkeypatch.setattr(ollama, "status", lambda: {"reachable": True, "llm_pulled": True, "embed_pulled": True})
    monkeypatch.setattr(ollama, "loaded", lambda: [
        {"name": "qwen3:4b-instruct", "size": 4000, "size_vram": 2680, "expires_at": "2026-09-28T10:30:00Z"}])
    monkeypatch.setattr(status.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="NVIDIA GeForce RTX 2050, 3712, 4096\n"))

    s = client.get("/admin/status").json()
    assert s["services"]["db"] == {"ok": True}
    assert s["llm"] == {"loaded": True, "model": "qwen3:4b-instruct", "gpu_share": 0.67,
                        "expires_at": "2026-09-28T10:30:00Z"}
    assert s["gpu"] == {"available": True, "name": "NVIDIA GeForce RTX 2050", "used_mib": 3712, "total_mib": 4096}
    assert s["answers"] == {"count": 0, "median_ms": None, "max_ms": None, "last_at": None}
    assert s["index"]["documents"] == 0 and s["index"]["excluded"] == 0 and s["index"]["db_bytes"] > 0

    with db.get_pool().connection() as conn:
        for ms in (4000, 8000, 60000):
            conn.execute("INSERT INTO query_log (question, latency_ms) VALUES ('q', %s)", (ms,))
    monkeypatch.setattr(ollama, "loaded", lambda: [])

    def no_smi(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(status.subprocess, "run", no_smi)
    s = client.get("/admin/status").json()
    assert s["llm"] == {"loaded": False, "model": "qwen3:4b-instruct"}
    assert s["gpu"] == {"available": False}
    assert s["answers"]["count"] == 3 and s["answers"]["median_ms"] == 8000 and s["answers"]["max_ms"] == 60000

    monkeypatch.setattr(ollama, "loaded", lambda: None)  # Ollama unreachable
    assert client.get("/admin/status").json()["llm"] is None
```

The status test pins `llm_model` to the default `qwen3:4b-instruct`. If `config.yaml` sets another model, compare against `get_settings().llm_model` instead.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_admin_api.py -q`
Expected: FAIL with 404s (no `/admin` routes).

- [ ] **Step 3: `ollama.loaded()`**

Add to `app/llm/ollama.py` after `status()`:

```python
def loaded() -> list[dict] | None:
    """Models Ollama holds in memory (/api/ps), with size and size_vram; None if Ollama is unreachable."""
    try:
        with _client(timeout=5) as c:
            return c.get("/api/ps").json().get("models", [])
    except httpx.HTTPError:
        return None
```

- [ ] **Step 4: `app/admin/status.py`**

```python
"""System status for the admin panel. Each part fails on its own: a broken part is null, never a 500."""

import logging
import statistics
import subprocess

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama

log = logging.getLogger(__name__)


def _services() -> dict:
    try:
        with get_pool().connection(timeout=3) as conn:
            conn.execute("SELECT 1")
        db = {"ok": True}
    except Exception as e:  # noqa: BLE001 -- reported to the user, not raised
        db = {"ok": False, "error": str(e)}
    return {"db": db, "ollama": ollama.status()}


def _llm() -> dict | None:
    models = ollama.loaded()
    if models is None:
        return None
    name = get_settings().llm_model
    m = next((m for m in models if m.get("name") in (name, f"{name}:latest")), None)
    if not m:
        return {"loaded": False, "model": name}
    share = m["size_vram"] / m["size"] if m.get("size") else 0.0
    return {"loaded": True, "model": name, "gpu_share": round(share, 2), "expires_at": m.get("expires_at")}


def _gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        ).stdout
        name, used, total = (x.strip() for x in out.strip().splitlines()[0].split(","))
        return {"available": True, "name": name, "used_mib": int(used), "total_mib": int(total)}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"available": False}


def _answers() -> dict:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT latency_ms, ts FROM query_log WHERE latency_ms IS NOT NULL ORDER BY id DESC LIMIT 20"
        ).fetchall()
    ms = sorted(r["latency_ms"] for r in rows)
    return {
        "count": len(rows),
        "median_ms": int(statistics.median(ms)) if ms else None,
        "max_ms": ms[-1] if ms else None,
        "last_at": rows[0]["ts"] if rows else None,
    }


def _index() -> dict:
    with get_pool().connection() as conn:
        return conn.execute(
            """SELECT (SELECT count(*) FROM documents) AS documents, (SELECT count(*) FROM chunks) AS chunks,
                      (SELECT count(*) FROM excluded_paths) AS excluded,
                      pg_database_size(current_database()) AS db_bytes"""
        ).fetchone()


def _safe(part):
    try:
        return part()
    except Exception:  # noqa: BLE001 -- one broken part must not blank the page
        log.exception("status part %s failed", part.__name__)
        return None


def status() -> dict:
    return {
        "services": _safe(_services),
        "llm": _safe(_llm),
        "gpu": _safe(_gpu) or {"available": False},
        "answers": _safe(_answers),
        "index": _safe(_index),
    }
```

- [ ] **Step 5: Shared job guard `app/api/jobs.py`**

```python
"""One index job at a time (rescan, re-index): a second request gets 409 instead of queueing behind the lock."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

_job = threading.Lock()


@contextmanager
def exclusive(what: str) -> Iterator[None]:
    if not _job.acquire(blocking=False):
        raise HTTPException(409, f"{what}: another rescan or re-index is running")
    try:
        yield
    finally:
        _job.release()
```

In `app/api/routes.py`, delete `_rescan_lock` and its `threading` import, and rewrite the endpoint:

```python
@router.post("/ingest/rescan")
def rescan_endpoint() -> dict:
    with exclusive("rescan"):
        return rescan()
```

with `from .jobs import exclusive`.

- [ ] **Step 6: Admin router `app/api/admin.py`**

```python
"""Admin panel: system status and library maintenance (exclude, include, forced re-index)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..admin.status import status
from ..config import get_settings
from ..db import get_pool
from ..ingest.pipeline import exclude, include, is_supported, reindex
from .jobs import exclusive

router = APIRouter(prefix="/admin")


class PathBody(BaseModel):
    path: str


class ReindexBody(BaseModel):
    path: str | None = None
    course: str | None = None


def _inbox_path(rel: str) -> tuple[str, Path]:
    """Normalised inbox-relative path and its absolute form; 400 if it escapes the inbox."""
    inbox = get_settings().inbox
    p = (inbox / rel).resolve()
    if not p.is_relative_to(inbox) or p == inbox:
        raise HTTPException(400, "path is outside the inbox")
    return p.relative_to(inbox).as_posix(), p


@router.get("/status")
def admin_status() -> dict:
    return status()


@router.get("/library")
def library() -> dict:
    inbox = get_settings().inbox
    with get_pool().connection() as conn:
        modules = conn.execute(
            """SELECT d.course, count(DISTINCT d.id) AS documents, count(c.id) AS chunks,
                      count(DISTINCT d.id) FILTER (WHERE d.status <> 'ok') AS problems
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.course ORDER BY d.course NULLS LAST"""
        ).fetchall()
        problems = conn.execute(
            """SELECT id, path, title, course, status, error FROM documents
               WHERE status <> 'ok' ORDER BY course NULLS LAST, title"""
        ).fetchall()
        excluded = conn.execute("SELECT path, excluded_at FROM excluded_paths ORDER BY path").fetchall()
    return {
        "modules": modules,
        "problems": problems,
        "excluded": [{**e, "on_disk": (inbox / e["path"]).is_file()} for e in excluded],
    }


@router.post("/reindex")
def admin_reindex(body: ReindexBody) -> dict:
    if (body.path is None) == (body.course is None):
        raise HTTPException(400, "give exactly one of path or course")
    if body.path is not None:
        rel, p = _inbox_path(body.path)
        if not (p.is_file() and is_supported(p)):
            raise HTTPException(404, "no such file in the inbox")
        with exclusive("re-index"):
            return reindex(rel=rel)
    rel, p = _inbox_path(body.course)
    if not p.is_dir():
        raise HTTPException(404, "no such module folder in the inbox")
    with exclusive("re-index"):
        return reindex(course=rel)


@router.post("/exclude")
def admin_exclude(body: PathBody) -> dict:
    rel, _ = _inbox_path(body.path)
    return {"removed": exclude(rel)}


@router.post("/include")
def admin_include(body: PathBody) -> dict:
    rel, _ = _inbox_path(body.path)
    result = include(rel)
    if result is None:
        raise HTTPException(404, "that file isn't excluded")
    return {"status": result}
```

In `app/main.py`, add `from .api.admin import router as admin_router` and `app.include_router(admin_router)` after the existing `include_router`.

- [ ] **Step 7: Run all tests and lint the new files**

Run: `uv run pytest -q && uv run ruff check --output-format concise app/admin app/api app/ingest app/llm/ollama.py tests`
Expected: 54 passed. The only ruff findings are the two that already existed (`routes.py` BLE001 in `/health` and the `test_pipeline.py` RUF059s); fix anything new.

- [ ] **Step 8: Commit**

```bash
git add backend/app/admin backend/app/llm/ollama.py backend/app/api/jobs.py backend/app/api/admin.py backend/app/api/routes.py backend/app/main.py backend/tests/test_admin_api.py
git commit -m "Admin API: status (services, LLM GPU share, VRAM, latency, index) and library actions"
```

---

### Task 4: Admin page, rail link

**Files:**
- Modify: `frontend/lib/api.ts` (types, `postJSON`)
- Create: `frontend/components/admin/StatusCard.tsx`, `frontend/components/admin/LibraryAdmin.tsx`
- Create: `frontend/app/admin/page.tsx`
- Modify: `frontend/components/Rail.tsx` (footer status line links to `/admin`)
- Modify: `frontend/app/globals.css` (admin styles)

**Interfaces:**
- Consumes: the Task 3 routes, `getJSON` (`lib/api.ts`), `ago` (`lib/seen.ts`), `moduleCode`/`tintVar` (`lib/modules.ts`), `callNumber` (`lib/api.ts`).
- Produces: route `/admin`.

- [ ] **Step 1: API types and `postJSON` (`lib/api.ts`)**

Append:

```ts
export type AdminStatus = {
  services: { db: { ok: boolean; error?: string }; ollama: Health["ollama"] } | null;
  llm:
    | { loaded: false; model: string }
    | { loaded: true; model: string; gpu_share: number; expires_at: string | null }
    | null;
  gpu: { available: false } | { available: true; name: string; used_mib: number; total_mib: number };
  answers: { count: number; median_ms: number | null; max_ms: number | null; last_at: string | null } | null;
  index: { documents: number; chunks: number; excluded: number; db_bytes: number } | null;
};

export type AdminLibrary = {
  modules: { course: string | null; documents: number; chunks: number; problems: number }[];
  problems: {
    id: number;
    path: string;
    title: string;
    course: string | null;
    status: "empty_text" | "error";
    error: string | null;
  }[];
  excluded: { path: string; excluded_at: string; on_disk: boolean }[];
};

/** POST JSON; throws with the backend's `detail` so the UI can show why an action failed. */
export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(`Can't reach the backend at ${API_URL}.`);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? `${path} returned ${res.status}`);
  return data as T;
}
```

- [ ] **Step 2: `components/admin/StatusCard.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { type AdminStatus, getJSON } from "@/lib/api";
import { ago } from "@/lib/seen";

const POLL_MS = 10_000;
const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const mb = (bytes: number) => `${(bytes / 2 ** 20).toFixed(0)} MB`;

function servicesLine(s: AdminStatus["services"]): { ok: boolean; text: string } {
  if (!s) return { ok: false, text: "Couldn't check the services." };
  if (!s.db.ok) return { ok: false, text: "Database offline. Run docker compose up." };
  if (!s.ollama.reachable) return { ok: false, text: "Ollama isn't running. Start it from the tray or run ollama serve." };
  if (!s.ollama.llm_pulled || !s.ollama.embed_pulled) return { ok: false, text: "A model isn't pulled yet. See the README setup." };
  return { ok: true, text: "Database, Ollama and both models ready" };
}

function llmLine(l: AdminStatus["llm"]): string {
  if (l === null) return "Unknown: Ollama isn't answering";
  if (!l.loaded) return `${l.model} · not loaded (the next question loads it, ~10 s)`;
  const until = l.expires_at ? ` · unloads ${new Date(l.expires_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "";
  return `${l.model} · ${Math.round(l.gpu_share * 100)}% on the GPU${until}`;
}

/** System status, refreshed every 10 s while the tab is visible. */
export function StatusCard() {
  const [s, setS] = useState<AdminStatus | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.visibilityState !== "visible") return;
      getJSON<AdminStatus>("/admin/status")
        .then((v) => {
          if (!alive) return;
          setS(v);
          setDown(false);
        })
        .catch(() => alive && setDown(true));
    };
    load();
    const t = window.setInterval(load, POLL_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      alive = false;
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);

  if (down && !s) return <p className="notice bad">Backend offline. Start it with uvicorn.</p>;
  if (!s) return <p className="muted">Checking the cabinet…</p>;

  const svc = servicesLine(s.services);
  const gpu = s.gpu;
  return (
    <section className="admin-card" aria-labelledby="status-h">
      <h2 id="status-h">Status</h2>
      {down && <p className="notice bad">Lost the backend. Showing the last reading.</p>}
      <dl className="kv">
        <dt>Services</dt>
        <dd className={svc.ok ? "ok" : "bad"}>{svc.text}</dd>

        <dt>LLM</dt>
        <dd>{llmLine(s.llm)}</dd>

        <dt>GPU</dt>
        <dd>
          {gpu.available ? (
            <>
              <span>
                {gpu.name} · {gpu.used_mib} / {gpu.total_mib} MiB
              </span>
              <meter className="vram" min={0} max={gpu.total_mib} value={gpu.used_mib} high={gpu.total_mib * 0.9}>
                {Math.round((gpu.used_mib / gpu.total_mib) * 100)}%
              </meter>
            </>
          ) : (
            "Unavailable (nvidia-smi not found)"
          )}
        </dd>

        <dt>Answers</dt>
        <dd>
          {!s.answers
            ? "–"
            : s.answers.count === 0
              ? "No questions asked yet"
              : `Median ${secs(s.answers.median_ms)}, slowest ${secs(s.answers.max_ms)} over the last ${s.answers.count} · last asked ${ago(s.answers.last_at)}`}
        </dd>

        <dt>Index</dt>
        <dd>
          {s.index
            ? `${s.index.documents} documents · ${s.index.chunks} chunks · ${s.index.excluded} excluded · ${mb(s.index.db_bytes)} on disk`
            : "–"}
        </dd>
      </dl>
    </section>
  );
}
```

- [ ] **Step 3: `components/admin/LibraryAdmin.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { type AdminLibrary, API_URL, getJSON, postJSON } from "@/lib/api";
import { moduleCode, tintVar } from "@/lib/modules";

type Note = { key: string; text: string; bad?: boolean } | null;

const counts = (r: Record<string, number>) =>
  Object.entries(r)
    .map(([k, n]) => `${n} ${k.replace("_", " ")}`)
    .join(", ") || "nothing to do";

/** Per-module counts, problem files, excluded files; rescan, re-index, exclude, include. */
export function LibraryAdmin() {
  const [lib, setLib] = useState<AdminLibrary | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note>(null);

  const reload = useCallback(() => {
    getJSON<AdminLibrary>("/admin/library")
      .then((l) => {
        setLib(l);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);
  useEffect(reload, [reload]);

  async function act(key: string, run: () => Promise<string>) {
    setBusy(key);
    setNote(null);
    try {
      setNote({ key, text: await run() });
    } catch (e) {
      setNote({ key, text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
      reload();
    }
  }

  const rescan = () =>
    act("rescan", async () => {
      const s = await postJSON<Record<string, number>>("/ingest/rescan", {});
      return `Rescanned: ${counts(s)}.`;
    });
  const reindex = (key: string, body: { path?: string; course?: string }) =>
    act(key, async () => `Re-indexed: ${counts(await postJSON<Record<string, number>>("/admin/reindex", body))}.`);
  const exclude = (path: string) =>
    act(`x:${path}`, async () => {
      const r = await postJSON<{ removed: boolean }>("/admin/exclude", { path });
      return r.removed ? "Excluded and removed from the index." : "Excluded.";
    });
  const include = (path: string) =>
    act(`i:${path}`, async () => {
      const r = await postJSON<{ status: string }>("/admin/include", { path });
      return r.status === "missing" ? "Included, but the file is no longer on disk." : `Included and filed (${r.status.replace("_", " ")}).`;
    });

  const inline = (key: string) =>
    note?.key === key && <span className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</span>;
  const btn = (key: string, label: string, onClick: () => void) => (
    <button type="button" className="quiet-btn" onClick={onClick} disabled={busy !== null}>
      {busy === key ? "Working…" : label}
    </button>
  );

  if (error && !lib) return <p className="notice bad">Couldn&apos;t load the library from {API_URL}.</p>;
  if (!lib) return <p className="muted">Counting the drawers…</p>;

  return (
    <section className="admin-card" aria-labelledby="library-h">
      <header className="admin-card-head">
        <h2 id="library-h">Library</h2>
        <span className="admin-actions">
          {inline("rescan")}
          {btn("rescan", "Rescan inbox", rescan)}
        </span>
      </header>

      <table className="admin-table">
        <thead>
          <tr>
            <th scope="col">Module</th>
            <th scope="col">Documents</th>
            <th scope="col">Chunks</th>
            <th scope="col">Problems</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lib.modules.map((m) => {
            const key = `m:${m.course}`;
            return (
              <tr key={m.course ?? ""}>
                <th scope="row">
                  <span className="label-card" style={{ "--tint": tintVar(m.course) } as React.CSSProperties}>
                    {moduleCode(m.course)}
                  </span>{" "}
                  {m.course ?? "Loose files"}
                </th>
                <td>{m.documents}</td>
                <td>{m.chunks}</td>
                <td>{m.problems || "–"}</td>
                <td className="row-actions">
                  {inline(key)}
                  {m.course && btn(key, "Re-index", () => reindex(key, { course: m.course! }))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Problem files</h3>
      {lib.problems.length === 0 ? (
        <p className="muted">Every file was read and indexed.</p>
      ) : (
        <ul className="admin-list">
          {lib.problems.map((p) => (
            <li key={p.id}>
              <span className="admin-item">
                <strong dir="auto">{p.title}</strong>
                <span className="callno">{p.path}</span>
                <span className="muted">
                  {p.status === "empty_text" ? "No text layer: a scanned file, not searchable yet" : p.error ?? "Couldn't be read"}
                </span>
              </span>
              <span className="row-actions">
                {inline(`r:${p.path}`)}
                {inline(`x:${p.path}`)}
                {btn(`r:${p.path}`, "Re-index", () => reindex(`r:${p.path}`, { path: p.path }))}
                {btn(`x:${p.path}`, "Exclude", () => exclude(p.path))}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Excluded</h3>
      {lib.excluded.length === 0 ? (
        <p className="muted">Nothing excluded. Exclude a file to keep it on disk but out of your answers.</p>
      ) : (
        <ul className="admin-list">
          {lib.excluded.map((e) => (
            <li key={e.path}>
              <span className="admin-item">
                <span className="callno">{e.path}</span>
                <span className="muted">
                  Excluded {new Date(e.excluded_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                  {e.on_disk ? "" : " · no longer on disk"}
                </span>
              </span>
              <span className="row-actions">
                {inline(`i:${e.path}`)}
                {btn(`i:${e.path}`, "Include", () => include(e.path))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

As the spec says, Exclude is offered on problem files. Healthy files are browsed on the Drawer page, which this sub-project doesn't change.

- [ ] **Step 4: `app/admin/page.tsx`**

```tsx
"use client";

import { LibraryAdmin } from "@/components/admin/LibraryAdmin";
import { StatusCard } from "@/components/admin/StatusCard";

export default function AdminPage() {
  return (
    <div className="drawer-view admin-view">
      <header className="drawer-head">
        <h1>Admin</h1>
        <p>The cabinet itself: services, GPU and the index</p>
      </header>
      <StatusCard />
      <LibraryAdmin />
    </div>
  );
}
```

- [ ] **Step 5: Rail footer link (`components/Rail.tsx`)**

Replace `<HealthLine health={health} />` with:

```tsx
        <Link href="/admin" className="health-link" aria-current={pathname.startsWith("/admin") ? "page" : undefined}>
          <HealthLine health={health} />
        </Link>
```

- [ ] **Step 6: Admin CSS**

Append to `app/globals.css`:

```css
/* ---- admin: the cabinet's own record cards ------------------------------------------------ */
.health-link {
  display: block;
  color: inherit;
  text-decoration: none;
  border-radius: 4px;
  margin: -0.15rem -0.3rem;
  padding: 0.15rem 0.3rem;
  transition: background-color 160ms var(--ease);
}

.health-link:hover,
.health-link[aria-current="page"] {
  background: var(--steel-2);
}

.admin-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.admin-card {
  background: var(--card);
  border-radius: 4px;
  box-shadow: var(--shadow);
  padding: 1rem 1.25rem 1.1rem;
}

.admin-card h2 {
  margin: 0 0 0.6rem;
  font-size: 1.02rem;
  font-weight: 600;
}

.admin-card h3 {
  margin: 1.4rem 0 0.4rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--muted);
}

.admin-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}

.kv {
  display: grid;
  grid-template-columns: 7rem minmax(0, 1fr);
  margin: 0;
}

.kv dt,
.kv dd {
  margin: 0;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--rule-blue);
}

.kv dt:last-of-type,
.kv dd:last-of-type {
  border-bottom: 0;
}

.kv dt {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--muted);
}

.kv dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.9rem;
}

.kv dd.ok {
  color: var(--good);
}

.kv dd.bad {
  color: var(--bad);
}

.vram {
  width: 12rem;
  height: 0.55rem;
}

.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.admin-table th,
.admin-table td {
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--rule-blue);
  text-align: start;
  font-weight: 400;
}

.admin-table thead th {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--muted);
}

.admin-table tbody tr:last-child > * {
  border-bottom: 0;
}

.label-card {
  display: inline-block;
  min-width: 3.4rem;
  padding: 0.08rem 0.35rem 0.03rem;
  border-radius: 2px;
  background: var(--tint);
  color: var(--ink);
  font-family: var(--type);
  font-weight: 700;
  font-size: 0.8rem;
  text-align: center;
}

.admin-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.admin-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--rule-blue);
}

.admin-list li:last-child {
  border-bottom: 0;
}

.admin-item {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.admin-item .callno {
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-actions,
.admin-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.action-note {
  font-size: 0.82rem;
  color: var(--good);
}

.action-note.bad {
  color: var(--bad);
}

@media (max-width: 860px) {
  .kv {
    grid-template-columns: minmax(0, 1fr);
  }
  .kv dt {
    padding-bottom: 0;
    border-bottom: 0;
  }
  .admin-list li {
    flex-direction: column;
    align-items: stretch;
  }
  .admin-table th:nth-child(3),
  .admin-table td:nth-child(3) {
    display: none; /* chunks: the least useful column on a phone */
  }
}
```

- [ ] **Step 7: Typecheck, lint, commit**

Run (in `frontend/`): `npx tsc --noEmit && npm run lint`. Expected: clean.

```bash
git add frontend/lib/api.ts frontend/components/admin frontend/app/admin frontend/components/Rail.tsx frontend/app/globals.css
git commit -m "Admin page: status card and library maintenance, linked from the rail footer"
```

---

### Task 5: Verify in the browser and polish

- [ ] **Step 1:** Restart the backend (`preview_start` "backend", so migration 004 applies) and open `/admin` in the frontend.
- [ ] **Step 2: Status.** Compare against `nvidia-smi` and `ollama ps` in the terminal: the VRAM numbers, the % on GPU (ask one question first so the LLM is loaded), and the index counts against `SELECT count(*)`. Stop Ollama briefly, or read the row when the LLM has unloaded, to see the "not loaded" line.
- [ ] **Step 3: Library.** Create `inbox/ZZ Admin Test/` with one `.md` note and one empty `.txt` (a problem file).
  1. Rescan: the module row appears, and the problem file is listed.
  2. Re-index the module: the counts note appears.
  3. Exclude the problem file: it moves to Excluded, and the module count drops.
  4. Include it again.
  5. Delete the folder in Explorer: the module disappears from the table after the watcher's debounce, with no manual rescan.
  6. Finally, rename a folder to check the move path, then delete the test folder.
- [ ] **Step 4:** The rail footer link works, shows its hover and current state, and the Drawer page no longer lists an excluded file.
- [ ] **Step 5:** Console is clear of errors. Mobile width has no horizontal scroll.
- [ ] **Step 6: Impeccable polish pass** against `DESIGN.md`: one batched inspection round (desktop + mobile), one fix batch, then stop.
- [ ] **Step 7:** Run `cd backend && uv run pytest -q` (54 passed) and `cd frontend && npx tsc --noEmit && npm run lint`, then commit any polish.
