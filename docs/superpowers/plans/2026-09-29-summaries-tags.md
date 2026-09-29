# Document Summaries and Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every indexed file gets a generated summary, key concepts and topic tags, which you can browse and filter in the library and reader and manage in `/admin`. Two retrieval experiments use the summaries and ship off by default.

**Architecture:**
- **Data:** migration 006 adds enrichment columns to `documents` and the `tags`, `tag_aliases` and `document_tags` tables.
- **`app/enrich/summarise.py`:** pure map-reduce over a document's chunks, through `ollama.chat_json`.
- **`app/enrich/worker.py`:** a background thread that picks one pending document at a time (`enriched_sha IS DISTINCT FROM sha256`). It waits while a question streams (`app/llm/busy.py`) or an index job runs, and writes results under a hash guard.
- **`app/enrich/vocab.py`:** merges raw tags into a per-module vocabulary by bge-m3 similarity, and implements rename, merge and delete.
- **Stage 3:** a summary boost in `_dense` and a summary line per passage in the prompt, both behind settings.

**Tech Stack:** FastAPI, psycopg 3 + pgvector, Ollama (`/api/chat` with a JSON-schema `format`, `/api/embed`), numpy, pytest (fake chat and embedder), Next.js client components.

**Spec:** `docs/superpowers/specs/2026-09-29-summaries-tags-design.md`

## Global Constraints

- **Ingest behaviour must not change.** Files become searchable exactly as today, and enrichment never takes the ingest `_lock`.
- **`/ask` output must not change** while `doc_boost = 0` and `doc_context = off`, the defaults.
- **Enrichment state:**
  - a document needs enrichment when `status = 'ok' AND enriched_sha IS DISTINCT FROM sha256`;
  - only `ok` and `error` are stored in `enrich_status`;
  - `pending` and `skipped` are derived by `ENRICH_STATE` (Task 3).
- **Output sizes:** summary 3–5 sentences in the document's language; 5–10 concepts; 3–8 tags. Tags are lowercased with whitespace collapsed, at most 40 characters each.
- **Budgets:** `GROUP_TOKENS = 2500` (bge-m3 token counts from `chunks.n_tokens`, which leaves room under `num_ctx` 4096); `REDUCE_FANIN = 8`.
- **Tag merging:** `tag_merge_threshold` defaults to 0.85. Embeddings are L2-normalised, so cosine is the dot product.
- **GPU sharing:** the worker makes at most one LLM call at a time. It waits while `busy.is_answering()` or `jobs.busy()`.
- **Backups and repository:** only `tags` and `tag_aliases` are added to the backup. No summaries, concepts or tags go into the repository.
- **Commands:**
  - backend commands run from `backend/` with `uv run`;
  - backend tests: `uv run pytest`;
  - frontend checks: `npx tsc --noEmit` and `npm run lint`, from `frontend/`;
  - frontend changes are verified in the browser preview.
- Commit messages follow the repo's style ("Area: what changed") and end with the `Co-Authored-By` line.

---

## Stage 1: summaries and concepts

### Task 1: Schema, settings, the "answering" gate

**Files:**
- Create: `backend/app/migrations/006_enrich.sql`, `backend/app/llm/busy.py`
- Modify:
  - `backend/app/config.py` (new settings)
  - `backend/app/api/jobs.py` (`busy()`)
  - `backend/app/rag/answer.py` (wrap `ask`)
  - `backend/app/admin/settings.py` (`save_local`)
  - `backend/app/main.py` (CORS `PATCH`)
- Test: `backend/tests/test_enrich.py` (new)

**Interfaces:**
- Produces:
  - `busy.answering()`, a context manager, and `busy.is_answering() -> bool`
  - `jobs.busy() -> bool`
  - `settings.save_local(key: str, value) -> None`
  - Settings fields `enrich_enabled: bool = True`, `enrich_paused: bool = False`, `tag_merge_threshold: float = 0.85`, `doc_boost: float = 0.0`, `doc_context: Literal["off", "on"] = "off"`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_enrich.py`)

```python
import threading
import time

import numpy as np
import pytest
from fakes import fake_embed, words
from psycopg.types.json import Jsonb


def test_migration_adds_enrichment_columns_and_tag_tables(env):
    _, db = env
    with db.get_pool().connection() as conn:
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'")}
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    assert {"summary", "concepts", "raw_tags", "enriched_sha", "enrich_status", "enrich_error",
            "summary_embedding"} <= cols
    assert "tags" not in cols
    assert {"tags", "tag_aliases", "document_tags"} <= tables


def test_ask_marks_answering_until_the_stream_ends_or_is_closed(env, monkeypatch):
    from app.llm import busy
    from app.rag import answer

    monkeypatch.setattr(answer, "retrieve", lambda q, c: ([], []))  # refused: no LLM call
    gen = answer.ask("anything?")
    assert not busy.is_answering()
    next(gen)
    assert busy.is_answering()
    list(gen)
    assert not busy.is_answering()

    gen = answer.ask("again?")
    next(gen)
    gen.close()  # the client went away mid-stream
    assert not busy.is_answering()


def test_save_local_writes_one_key(tmp_path, monkeypatch):
    from app import config
    from app.admin import settings

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    settings.save_local("enrich_paused", True)
    assert config.get_settings().enrich_paused is True
    settings.save_local("enrich_paused", False)
    assert config.get_settings().enrich_paused is False
    config.get_settings.cache_clear()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: FAIL. The columns are missing, `app.llm.busy` doesn't exist, and `save_local` isn't defined.

- [ ] **Step 3: Write the migration** (`backend/app/migrations/006_enrich.sql`)

```sql
-- Summaries, concepts and tags per document (app.enrich). pending/skipped are derived, not stored:
-- see ENRICH_STATE in app/enrich/worker.py.
ALTER TABLE documents
    ADD COLUMN concepts           JSONB,
    ADD COLUMN raw_tags           JSONB,
    ADD COLUMN enriched_sha       TEXT,
    ADD COLUMN enrich_status      TEXT CHECK (enrich_status IN ('ok', 'error')),
    ADD COLUMN enrich_error       TEXT,
    ADD COLUMN summary_embedding  vector(1024);
ALTER TABLE documents DROP COLUMN tags;

CREATE TABLE tags (
    id          BIGSERIAL PRIMARY KEY,
    course      TEXT,
    name        TEXT NOT NULL,
    user_named  BOOLEAN NOT NULL DEFAULT false,
    UNIQUE NULLS NOT DISTINCT (course, name)
);
CREATE TABLE tag_aliases (
    id          BIGSERIAL PRIMARY KEY,
    course      TEXT,
    raw         TEXT NOT NULL,
    tag_id      BIGINT REFERENCES tags(id) ON DELETE CASCADE,  -- NULL: you deleted the tag; drop this raw tag
    UNIQUE NULLS NOT DISTINCT (course, raw)
);
CREATE TABLE document_tags (
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);
CREATE INDEX document_tags_tag_idx ON document_tags (tag_id);
```

- [ ] **Step 4: Add the settings** (`backend/app/config.py`, after `sync_auto_days`)

```python
    # Summaries, concepts and tags per document (app.enrich), made in the background after ingest
    enrich_enabled: bool = True
    enrich_paused: bool = False  # Pause/Resume in the admin panel writes this to config.local.yaml
    tag_merge_threshold: float = 0.85  # cosine at which a raw tag joins an existing tag

    # Retrieval experiments with summaries (off unless the evaluation shows a gain)
    doc_boost: float = 0.0  # adds doc_boost x similarity(question, file summary) to each passage's score
    doc_context: Literal["off", "on"] = "off"  # on: each passage in the prompt gets its file's summary line
```

- [ ] **Step 5: Write the gate** (`backend/app/llm/busy.py`)

```python
"""Is a question being answered right now? Background LLM work (enrichment) waits while one is."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_count = 0
_lock = threading.Lock()


@contextmanager
def answering() -> Iterator[None]:
    global _count
    with _lock:
        _count += 1
    try:
        yield
    finally:
        with _lock:
            _count -= 1


def is_answering() -> bool:
    return _count > 0
```

- [ ] **Step 6: Wrap `ask`** (`backend/app/rag/answer.py`)

Rename the existing `def ask(question: str, course: str | None = None)` to `def _ask(...)`, keeping its body unchanged. Add `from ..llm import busy` to the imports, and add above `_ask`:

```python
def ask(question: str, course: str | None = None) -> Iterator[tuple[str, dict]]:
    with busy.answering():  # background enrichment keeps off the GPU until the stream ends or is closed
        yield from _ask(question, course)
```

- [ ] **Step 7: Add `jobs.busy`** (`backend/app/api/jobs.py`, at the end)

```python
def busy() -> bool:
    """Is an index job (rescan, re-index, evaluation) running? Background enrichment waits for it."""
    return _job.locked()
```

- [ ] **Step 8: Add `save_local`** (`backend/app/admin/settings.py`)

Replace the write block at the end of `update()`, from `path = config.LOCAL_CONFIG` through `config.get_settings.cache_clear()`, with `_write_local(new_local)`. Then add these two functions above `update()`:

```python
def _write_local(new_local: dict) -> None:
    path = config.LOCAL_CONFIG
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write("# Written by the admin panel. Overrides config.yaml; environment variables override this.\n")
        yaml.safe_dump(dict(sorted(new_local.items())), tmp, allow_unicode=True)
    os.replace(tmp.name, path)
    config.get_settings.cache_clear()


def save_local(key: str, value) -> None:
    """Set one key in config.local.yaml directly: panel controls that aren't form settings (pausing enrichment)."""
    _write_local({**_yaml(config.LOCAL_CONFIG), key: value})
```

- [ ] **Step 9: Allow `PATCH`** (`backend/app/main.py`)

```python
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
```

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_enrich.py tests/test_settings.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all PASS. Nothing else reads `documents.tags`; if a test fails on it, `grep -rn "\.tags\|'tags'" app` and remove the reference.

- [ ] **Step 11: Commit**

```bash
git add backend/app/migrations/006_enrich.sql backend/app/llm/busy.py backend/app/config.py backend/app/api/jobs.py backend/app/rag/answer.py backend/app/admin/settings.py backend/app/main.py backend/tests/test_enrich.py
git commit -m "Enrich: schema for summaries and tags, settings, and an answering gate for background LLM work"
```

---

### Task 2: Map-reduce summarising

**Files:**
- Create: `backend/app/enrich/__init__.py` (empty), `backend/app/enrich/summarise.py`
- Test: `backend/tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `ollama.OllamaError`; `lang.detect(text) -> "fr" | "en" | "ar"`; `lang.NAMES`
- Produces:
  - `summarise.GROUP_TOKENS = 2500`, `summarise.REDUCE_FANIN = 8`
  - `summarise.BadOutput(ValueError)`
  - `summarise.groups(chunks: list[dict], budget: int = GROUP_TOKENS) -> list[list[dict]]`
  - `summarise.clean(out: dict) -> dict`
  - `summarise.summarise(title: str, chunks: list[dict], chat) -> dict` with `{summary: str, concepts: list[str], tags: list[str]}`. `chunks` are `{"text", "n_tokens"}` in order; `chat(messages, schema) -> dict`. Raises `BadOutput`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_enrich.py`)

```python
GOOD = {"summary": "Un résumé.", "concepts": ["Gradient descent", "gradient descent", " Loss ", ""],
        "tags": ["Optimization", "optimization", "  Stochastic   GD ", "x" * 41]}


def recording_chat(calls, reply=None):
    def chat(messages, schema, temperature=0.3):
        calls.append(messages)
        return reply(len(calls)) if reply else {**GOOD, "summary": f"Summary {len(calls)}."}
    return chat


def test_groups_respect_the_budget_and_never_split_a_chunk():
    from app.enrich.summarise import groups

    chunks = [{"text": "x", "n_tokens": n} for n in (1000, 1000, 600, 2600, 100)]
    assert [[c["n_tokens"] for c in g] for g in groups(chunks, budget=2500)] == [[1000, 1000], [600], [2600], [100]]
    assert groups([]) == []


def test_clean_trims_dedupes_and_lowercases_tags():
    from app.enrich.summarise import clean

    assert clean(GOOD) == {"summary": "Un résumé.", "concepts": ["Gradient descent", "Loss"],
                           "tags": ["optimization", "stochastic gd"]}


def test_short_file_is_one_call():
    from app.enrich.summarise import summarise

    calls = []
    out = summarise("Chap 1", [{"text": "Le gradient est un vecteur de dérivées partielles.", "n_tokens": 300}],
                    recording_chat(calls))
    assert len(calls) == 1 and out["summary"] == "Summary 1."
    assert "French" in calls[0][0]["content"] and "Chap 1" in calls[0][1]["content"]


def test_long_file_maps_then_reduces():
    from app.enrich.summarise import summarise

    calls = []
    summarise("Deck", [{"text": "the cluster runs pods", "n_tokens": 2000} for _ in range(3)], recording_chat(calls))
    assert len(calls) == 4
    assert "Part 1 of 3" in calls[0][1]["content"] and "Part 3 of 3" in calls[2][1]["content"]
    assert "Summary 1." in calls[3][1]["content"] and "Summary 3." in calls[3][1]["content"]


def test_many_parts_reduce_in_rounds():
    from app.enrich.summarise import summarise

    calls = []
    summarise("Deck", [{"text": "slide", "n_tokens": 2500} for _ in range(20)], recording_chat(calls))
    assert len(calls) == 20 + 3 + 1  # 20 maps, then ceil(20/8) = 3 reductions, then 1


def test_bad_output_is_retried_once_then_raises():
    from app.enrich.summarise import BadOutput, summarise

    one = [{"text": "text", "n_tokens": 10}]
    calls = []
    out = summarise("F", one, recording_chat(calls, lambda n: {"summary": ""} if n == 1 else GOOD))
    assert len(calls) == 2 and "JSON only" in calls[1][0]["content"] and out["summary"] == "Un résumé."

    with pytest.raises(BadOutput):
        summarise("F", one, recording_chat([], lambda n: {"summary": "no lists"}))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py -k "groups or clean or file or parts or bad_output" -v`
Expected: FAIL with `ModuleNotFoundError: app.enrich`.

- [ ] **Step 3: Implement** (`backend/app/enrich/summarise.py`, plus an empty `backend/app/enrich/__init__.py`)

```python
"""Summary, key concepts and raw tags for one document: one call for a short file, map-reduce for a long one."""

from collections.abc import Callable

from ..llm.lang import NAMES, detect
from ..llm.ollama import OllamaError

GROUP_TOKENS = 2500  # bge-m3 tokens of chunk text per call; leaves room in num_ctx 4096 for the prompt and reply
REDUCE_FANIN = 8     # part descriptions combined per reduce call
MAX_TAG_CHARS = 40

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "concepts", "tags"],
}
SYSTEM = (
    "You describe a file from a university student's course material, so they can see what it covers. "
    "Reply as JSON with: summary (3 to 5 sentences), concepts (5 to 10 key concepts, short noun phrases), "
    "tags (3 to 8 short topic labels of 1 to 3 words, general enough that other files could share them). "
    "Write the summary and concepts in {language}. Use only what the text says."
)
REDUCE_NOTE = " You get descriptions of consecutive parts of one file: describe the whole file."
STRICT = " Reply with JSON only, with exactly the keys summary, concepts and tags."
ONE = "File: {title}\n\n{text}"
PART = "File: {title}\nPart {i} of {n}.\n\n{text}"
PARTS = "File: {title}\n\n{parts}"

Chat = Callable[[list[dict], dict], dict]


class BadOutput(ValueError):
    """The model's reply wasn't usable, even after one stricter retry."""


def groups(chunks: list[dict], budget: int = GROUP_TOKENS) -> list[list[dict]]:
    """Consecutive chunks, at most `budget` tokens per group. A chunk is never split; an oversize one stands alone."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    used = 0
    for c in chunks:
        if cur and used + c["n_tokens"] > budget:
            out.append(cur)
            cur, used = [], 0
        cur.append(c)
        used += c["n_tokens"]
    if cur:
        out.append(cur)
    return out


def _dedupe(items: list[str], cap: int) -> list[str]:
    seen: set[str] = set()
    out = []
    for it in items:
        if it and it.lower() not in seen:
            seen.add(it.lower())
            out.append(it)
    return out[:cap]


def clean(out: dict) -> dict:
    summary = str(out.get("summary") or "").strip()
    concepts, tags = out.get("concepts"), out.get("tags")
    if not summary or not isinstance(concepts, list) or not isinstance(tags, list):
        raise BadOutput("the model's reply is missing a summary, concepts or tags")
    return {
        "summary": summary,
        "concepts": _dedupe([" ".join(str(c).split()) for c in concepts], 10),
        "tags": _dedupe([t for t in (" ".join(str(t).lower().split()) for t in tags) if len(t) <= MAX_TAG_CHARS], 8),
    }


def _call(chat: Chat, system: str, user: str) -> dict:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return clean(chat(messages, SCHEMA))
    except (BadOutput, OllamaError):
        messages[0] = {"role": "system", "content": system + STRICT}
        try:
            return clean(chat(messages, SCHEMA))
        except OllamaError as e:
            raise BadOutput(str(e)) from e


def _join(group: list[dict]) -> str:
    return "\n\n".join(c["text"] for c in group)


def _render(part: dict) -> str:
    return f"{part['summary']}\nConcepts: {', '.join(part['concepts'])}\nTags: {', '.join(part['tags'])}"


def summarise(title: str, chunks: list[dict], chat: Chat) -> dict:
    """{summary, concepts, tags} for a document's chunks (in order). Raises BadOutput."""
    if not chunks:
        raise BadOutput("no indexed text")
    system = SYSTEM.format(language=NAMES[detect(" ".join(c["text"] for c in chunks[:3]))])
    parts = groups(chunks)
    if len(parts) == 1:
        return _call(chat, system, ONE.format(title=title, text=_join(parts[0])))
    results = [_call(chat, system, PART.format(title=title, i=i, n=len(parts), text=_join(g)))
               for i, g in enumerate(parts, start=1)]
    while len(results) > 1:
        results = [
            _call(chat, system + REDUCE_NOTE,
                  PARTS.format(title=title, parts="\n\n".join(_render(r) for r in results[i:i + REDUCE_FANIN])))
            for i in range(0, len(results), REDUCE_FANIN)
        ]
    return results[0]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/enrich/__init__.py backend/app/enrich/summarise.py backend/tests/test_enrich.py
git commit -m "Enrich: summary, concepts and tags per file, one call for short files and map-reduce for long ones"
```

---

### Task 3: The enrichment worker

**Files:**
- Create: `backend/app/enrich/worker.py`
- Modify: `backend/app/main.py` (start and stop the worker)
- Test: `backend/tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `summarise.summarise`, `summarise.BadOutput`, `busy.is_answering`, `jobs.busy`, `settings.save_local`, `ollama.chat_json`
- Produces:
  - `worker.ENRICH_STATE`: an SQL expression over unqualified `documents` columns, returning `'pending' | 'ok' | 'error' | 'skipped'`
  - `worker.counts() -> dict` with `{ok, error, pending, skipped}`
  - `class Enricher(chat=None, embed=None, idle: float = 30, poll: float = 1.0)`, with methods:
    - `step() -> bool`
    - `start()`, `stop()`, `wake()`
    - `pause()`, `resume()`
    - `rerun(course: str | None = None, document_id: int | None = None) -> int`
    - `status() -> dict` with `{state, current, last_error, paused, enabled, counts}`
    - `_after_write(doc: dict, ok: bool) -> None`: a hook that Tasks 6 and 9 fill in
  - the module singleton `worker = Enricher()`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_enrich.py`)

```python
def add_doc(db, path, course="Course0", sha="a", status="ok", texts=("Le gradient est un vecteur.",)):
    with db.get_pool().connection() as conn:
        doc_id = conn.execute(
            """INSERT INTO documents (path, sha256, course, title, mime, status)
               VALUES (%s, %s, %s, %s, 'text/markdown', %s) RETURNING id""",
            (path, sha, course, path.rsplit("/", 1)[-1], status),
        ).fetchone()["id"]
        for i, t in enumerate(texts):
            conn.execute(
                "INSERT INTO chunks (document_id, ord, page, text, n_tokens, embedding) VALUES (%s, %s, 1, %s, %s, %s)",
                (doc_id, i, t, len(t.split()), fake_embed([t])[0]),
            )
    return doc_id


def doc(db, doc_id):
    with db.get_pool().connection() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()


def good_chat(messages, schema, temperature=0.3):
    return dict(GOOD)


def test_step_enriches_pending_documents_oldest_first(env):
    from app.enrich.worker import Enricher, counts

    _, db = env
    a = add_doc(db, "Course0/a.md")
    b = add_doc(db, "Course0/b.md")
    add_doc(db, "Course0/scan.pdf", status="empty_text", texts=())
    assert counts() == {"ok": 0, "error": 0, "pending": 2, "skipped": 1}

    e = Enricher(chat=good_chat, embed=fake_embed)
    assert e.step() is True
    assert doc(db, a)["summary"] == "Un résumé." and doc(db, a)["enrich_status"] == "ok"
    assert doc(db, a)["concepts"] == ["Gradient descent", "Loss"] and doc(db, a)["raw_tags"] == ["optimization", "stochastic gd"]
    assert doc(db, b)["summary"] is None
    assert e.step() is True and e.step() is False
    assert counts() == {"ok": 2, "error": 0, "pending": 0, "skipped": 1}


def test_changed_file_is_requeued_but_a_forced_reindex_of_the_same_file_is_not(env):
    from app.enrich.worker import Enricher, counts
    from app.ingest.pipeline import ingest_file

    inbox, db = env
    f = inbox / "Course0" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("Le gradient est un vecteur de dérivées partielles.", encoding="utf-8")
    ingest_file(f, fake_embed, words)
    Enricher(chat=good_chat, embed=fake_embed).step()
    assert counts()["pending"] == 0

    ingest_file(f, fake_embed, words, force=True)
    assert counts()["pending"] == 0
    f.write_text("La hessienne est la matrice des dérivées secondes.", encoding="utf-8")
    ingest_file(f, fake_embed, words)
    assert counts()["pending"] == 1


def test_bad_output_is_an_error_and_the_file_stays_searchable(env):
    from app.enrich.worker import Enricher, counts

    _, db = env
    a = add_doc(db, "Course0/a.md")
    Enricher(chat=lambda m, s, temperature=0.3: {"summary": ""}, embed=fake_embed).step()
    d = doc(db, a)
    assert d["enrich_status"] == "error" and "missing a summary" in d["enrich_error"] and d["enriched_sha"] == "a"
    assert counts()["error"] == 1  # stored with the hash: not retried in a loop
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s", (a,)).fetchone()["n"] == 1


def test_a_file_that_changes_mid_summary_is_not_overwritten(env):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")

    def chat(messages, schema, temperature=0.3):
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE documents SET sha256 = 'b' WHERE id = %s", (a,))
        return dict(GOOD)

    Enricher(chat=chat, embed=fake_embed).step()
    d = doc(db, a)
    assert d["summary"] is None and d["enriched_sha"] is None  # still pending, for the new content


def test_no_llm_call_while_a_question_streams(env):
    from app.enrich.worker import Enricher
    from app.llm import busy

    _, db = env
    add_doc(db, "Course0/a.md")
    calls = []
    e = Enricher(chat=lambda m, s, temperature=0.3: calls.append(1) or dict(GOOD), embed=fake_embed, poll=0.01)
    with busy.answering():
        t = threading.Thread(target=e.step)
        t.start()
        time.sleep(0.2)
        assert calls == [] and e.status()["state"] == "waiting"
    t.join(2)
    assert calls == [1]


def test_pause_resume_and_rerun(env, tmp_path, monkeypatch):
    from app import config
    from app.enrich.worker import Enricher, counts

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    _, db = env
    a = add_doc(db, "Course0/a.md")
    add_doc(db, "Course1/b.md", course="Course1")
    e = Enricher(chat=good_chat, embed=fake_embed)
    e.pause()
    assert e.step() is False and e.status()["paused"] is True
    e.resume()
    assert e.step() and e.step()
    assert e.rerun(course="Course0") == 1 and counts()["pending"] == 1
    assert e.rerun(document_id=a) == 1
    config.get_settings.cache_clear()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: the new tests FAIL with `ModuleNotFoundError: app.enrich.worker`.

- [ ] **Step 3: Implement** (`backend/app/enrich/worker.py`)

```python
"""Background enrichment: one document at a time, oldest first, off the GPU while a question streams.

A document needs enrichment when status = 'ok' and enriched_sha differs from sha256, so a changed file
is queued again by ingest on its own. Results are written only if the file hasn't changed meanwhile.
"""

import logging
import threading

import httpx
from psycopg.types.json import Jsonb

from ..admin.settings import save_local
from ..api import jobs
from ..config import get_settings
from ..db import get_pool
from ..llm import busy, ollama
from .summarise import BadOutput, summarise

log = logging.getLogger(__name__)

# The state a document shows. Unqualified column names: valid wherever `documents` is joined with `chunks`.
ENRICH_STATE = """CASE WHEN status <> 'ok' THEN 'skipped'
                       WHEN enriched_sha IS DISTINCT FROM sha256 THEN 'pending'
                       ELSE enrich_status END"""
PENDING = "status = 'ok' AND enriched_sha IS DISTINCT FROM sha256"


class _Stopped(Exception):
    pass


def counts() -> dict:
    out = dict.fromkeys(("ok", "error", "pending", "skipped"), 0)
    with get_pool().connection() as conn:
        for r in conn.execute(f"SELECT {ENRICH_STATE} AS s, count(*) AS n FROM documents GROUP BY 1"):
            out[r["s"]] = r["n"]
    return out


class Enricher:
    def __init__(self, chat=None, embed=None, idle: float = 30, poll: float = 1.0):
        self.chat, self.embed = chat, embed  # None: the real Ollama calls, looked up per use
        self.idle, self.poll = idle, poll
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = {"state": "idle", "current": None, "last_error": None}
        self._backoff = 0.0

    # --- control --------------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="enrich", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(5)

    def wake(self) -> None:
        self._wake.set()

    def pause(self) -> None:
        save_local("enrich_paused", True)

    def resume(self) -> None:
        save_local("enrich_paused", False)
        self.wake()

    def rerun(self, course: str | None = None, document_id: int | None = None) -> int:
        """Queue a module or one file again. Returns how many documents were queued."""
        with get_pool().connection() as conn:
            n = conn.execute(
                "UPDATE documents SET enriched_sha = NULL WHERE status = 'ok' AND (id = %s OR course = %s)",
                (document_id, course),
            ).rowcount
        self.wake()
        return n

    def status(self) -> dict:
        s = get_settings()
        with self._lock:
            state = dict(self._state)
        if not s.enrich_enabled:
            state["state"] = "off"
        return {**state, "paused": s.enrich_paused, "enabled": s.enrich_enabled, "counts": counts()}

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    # --- work -----------------------------------------------------------------------------
    def _gate(self) -> bool:
        """Wait while paused, while a question streams or while an index job runs. False when stopping."""
        while not self._stop.is_set():
            if get_settings().enrich_paused:
                self._set(state="paused")
            elif busy.is_answering() or jobs.busy():
                self._set(state="waiting")
            else:
                self._set(state="running")
                return True
            self._stop.wait(self.poll)
        return False

    def step(self) -> bool:
        """Enrich the next pending document. False when there's nothing to do, or when paused or stopping."""
        s = get_settings()
        if not s.enrich_enabled or s.enrich_paused:
            return False
        with get_pool().connection() as conn:
            doc = conn.execute(
                f"SELECT id, sha256, title, course FROM documents WHERE {PENDING} ORDER BY ingested_at, id LIMIT 1"
            ).fetchone()
            if doc is None:
                return False
            chunks = conn.execute(
                "SELECT text, n_tokens FROM chunks WHERE document_id = %s ORDER BY ord", (doc["id"],)
            ).fetchall()
        chat = self.chat or ollama.chat_json

        def gated(messages, schema):
            if not self._gate():
                raise _Stopped
            return chat(messages, schema)

        self._set(current=doc["title"])
        try:
            out, error = summarise(doc["title"], chunks, gated), None
        except BadOutput as e:
            out, error = None, str(e)
        except _Stopped:
            return False
        self._write(doc, out, error)
        return True

    def _write(self, doc: dict, out: dict | None, error: str | None) -> None:
        with get_pool().connection() as conn, conn.transaction():
            if out:
                n = conn.execute(
                    """UPDATE documents SET summary = %s, concepts = %s, raw_tags = %s, enriched_sha = sha256,
                              enrich_status = 'ok', enrich_error = NULL, summary_embedding = NULL
                       WHERE id = %s AND sha256 = %s""",
                    (out["summary"], Jsonb(out["concepts"]), Jsonb(out["tags"]), doc["id"], doc["sha256"]),
                ).rowcount
            else:
                n = conn.execute(
                    """UPDATE documents SET summary = NULL, concepts = NULL, raw_tags = NULL, enriched_sha = sha256,
                              enrich_status = 'error', enrich_error = %s, summary_embedding = NULL
                       WHERE id = %s AND sha256 = %s""",
                    (error, doc["id"], doc["sha256"]),
                ).rowcount
        if n == 0:
            log.info("%s changed while it was summarised; it stays queued", doc["title"])
            return
        self._set(last_error=error)
        self._after_write(doc, ok=out is not None)

    def _after_write(self, doc: dict, ok: bool) -> None:
        """Tags (stage 2) and the summary embedding (stage 3) hook in here."""

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                did = self.step()
                self._backoff = 0.0
            except httpx.HTTPError as e:  # Ollama unreachable: back off; the document stays pending
                self._backoff = min(max(5.0, self._backoff * 2), 300.0)
                self._set(state="waiting for Ollama", last_error=str(e))
                self._stop.wait(self._backoff)
                continue
            except Exception as e:  # a bad step must not kill the thread
                log.exception("enrichment step failed")
                self._set(last_error=f"{type(e).__name__}: {e}")
                did = False
            if not did:
                self._set(state="paused" if get_settings().enrich_paused else "idle", current=None)
                self._wake.wait(self.idle)
                self._wake.clear()


worker = Enricher()
```

- [ ] **Step 4: Start the worker with the backend** (`backend/app/main.py`)

Add `from .enrich.worker import worker as enricher` to the imports. In `lifespan`, after `backups.start()`, add:

```python
    if get_settings().enrich_enabled:
        enricher.start()
```

At the start of the shutdown section, before `backups.stop()`, add:

```python
    enricher.stop()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/enrich/worker.py backend/app/main.py backend/tests/test_enrich.py
git commit -m "Enrich: background worker, one file at a time, waits for questions and index jobs, hash-guarded writes"
```

---

### Task 4: API for summaries and enrichment control

**Files:**
- Modify:
  - `backend/app/api/routes.py` (`/documents` and `/documents/{id}/pages` fields)
  - `backend/app/api/admin.py` (enrich routes; `summary_errors` in `/admin/library`)
  - `backend/app/admin/status.py` (the `enrichment` part)
- Test: `backend/tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `worker.ENRICH_STATE`, `worker.worker`
- Produces:
  - `GET /documents` rows gain `summary: str | null`, `concepts: list | null`, `enrich_status`, `enrich_error`
  - `GET /documents/{id}/pages` gains the same four fields
  - `GET /admin/enrich` returns `worker.status()`
  - `POST /admin/enrich/pause` and `/resume` return the status
  - `POST /admin/enrich/rerun`, with `{course}` or `{document_id}`, returns `{"queued": n}`
  - `GET /admin/library` gains `summary_errors: [{id, path, title, course, error}]`
  - `GET /admin/status` gains `enrichment`: the same shape as `GET /admin/enrich`, or null

- [ ] **Step 1: Write the failing tests** (append)

```python
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import config
    from app.main import create_app

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    return TestClient(create_app())  # no `with`: no lifespan, so no background worker


def test_documents_carry_summary_fields(env, monkeypatch, tmp_path):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    b = add_doc(db, "Course0/b.md")
    Enricher(chat=good_chat, embed=fake_embed).step()
    rows = {r["id"]: r for r in client(monkeypatch, tmp_path).get("/documents").json()}
    assert rows[a]["summary"] == "Un résumé." and rows[a]["concepts"] == ["Gradient descent", "Loss"]
    assert (rows[a]["enrich_status"], rows[b]["enrich_status"]) == ("ok", "pending")


def test_enrich_admin_routes(env, monkeypatch, tmp_path):
    _, db = env
    add_doc(db, "Course0/a.md")
    c = client(monkeypatch, tmp_path)
    assert c.get("/admin/enrich").json()["counts"]["pending"] == 1
    assert c.post("/admin/enrich/pause").json()["paused"] is True
    assert c.post("/admin/enrich/resume").json()["paused"] is False
    assert c.post("/admin/enrich/rerun", json={}).status_code == 400
    assert c.post("/admin/enrich/rerun", json={"course": "Course0"}).json() == {"queued": 1}
    assert c.get("/admin/status").json()["enrichment"]["counts"]["pending"] == 1


def test_library_lists_files_that_could_not_be_summarised(env, monkeypatch, tmp_path):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    Enricher(chat=lambda m, s, temperature=0.3: {"summary": ""}, embed=fake_embed).step()
    errors = client(monkeypatch, tmp_path).get("/admin/library").json()["summary_errors"]
    assert [e["id"] for e in errors] == [a] and "missing a summary" in errors[0]["error"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py -k "documents_carry or admin_routes or could_not" -v`
Expected: FAIL with a `KeyError` on `summary`, a 404 on `/admin/enrich`, and a `KeyError` on `summary_errors`.

- [ ] **Step 3: Add the fields to `/documents` and `/documents/{id}/pages`** (`backend/app/api/routes.py`)

Add `from ..enrich.worker import ENRICH_STATE` to the imports. In `documents()`, change the SELECT list to:

```python
            f"""SELECT d.id, d.path, d.title, d.course, d.mime, d.page_count, d.status, d.error,
                      d.mtime, d.ingested_at, d.first_seen, count(c.id) AS chunk_count,
                      d.summary, d.concepts, d.enrich_error, {ENRICH_STATE} AS enrich_status
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.id ORDER BY d.course NULLS LAST, d.title"""
```

In `document_pages()`, change the columns argument to:

```python
    row, path = _document_file(
        doc_id, f"id, path, title, course, mime, page_count, status, error, ingested_at, "
                f"summary, concepts, enrich_error, {ENRICH_STATE} AS enrich_status"
    )
```

- [ ] **Step 4: Add the admin routes** (`backend/app/api/admin.py`)

Add `from ..enrich.worker import worker as enricher` to the imports, then:

```python
class RerunBody(BaseModel):
    course: str | None = None
    document_id: int | None = None


@router.get("/enrich")
def enrich_status() -> dict:
    return enricher.status()


@router.post("/enrich/pause")
def enrich_pause() -> dict:
    enricher.pause()
    return enricher.status()


@router.post("/enrich/resume")
def enrich_resume() -> dict:
    enricher.resume()
    return enricher.status()


@router.post("/enrich/rerun")
def enrich_rerun(body: RerunBody) -> dict:
    if (body.course is None) == (body.document_id is None):
        raise HTTPException(400, "give exactly one of course or document_id")
    return {"queued": enricher.rerun(course=body.course, document_id=body.document_id)}
```

In `library()`, add this query inside the `with` block:

```python
        summary_errors = conn.execute(
            """SELECT id, path, title, course, enrich_error AS error FROM documents
               WHERE status = 'ok' AND enriched_sha = sha256 AND enrich_status = 'error'
               ORDER BY course NULLS LAST, title"""
        ).fetchall()
```

Add `"summary_errors": summary_errors,` to the returned dict.

- [ ] **Step 5: Add enrichment to the status** (`backend/app/admin/status.py`)

```python
def _enrichment() -> dict:
    from ..enrich.worker import worker

    return worker.status()
```

Add `"enrichment": _safe(_enrichment),` to the dict in `status()`.

- [ ] **Step 6: Run all the tests**

Run: `uv run pytest`
Expected: all PASS. If `test_admin_api.py` compares `/admin/library` or `/admin/status` keys exactly, add `summary_errors` and `enrichment` to its expectations.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes.py backend/app/api/admin.py backend/app/admin/status.py backend/tests/
git commit -m "Enrich API: summaries on documents, enrichment status, pause, resume and re-enrich"
```

---

### Task 5: Frontend for summaries (library, reader, admin), README, first backfill

**Files:**
- Create: `frontend/components/DocSummary.tsx`
- Modify:
  - `frontend/lib/api.ts` (types; `sendJSON` methods)
  - `frontend/app/documents/page.tsx`
  - `frontend/app/documents/[id]/page.tsx`
  - `frontend/components/admin/StatusCard.tsx`
  - `frontend/components/admin/LibraryAdmin.tsx`
  - `frontend/app/globals.css`
  - `README.md`

**Interfaces:**
- Consumes: the Task 4 API
- Produces:
  - TS types `EnrichStatus`, `EnrichmentStatus`
  - `DocumentRow` fields `summary`, `concepts`, `enrich_status`, `enrich_error`
  - `sendJSON` accepts `"PATCH" | "DELETE"`
  - the `<DocSummary doc={...} />` component, which Task 8 extends with tags

- [ ] **Step 1: Types** (`frontend/lib/api.ts`)

Add the following to `DocumentRow`, after `chunk_count`:

```ts
  /** generated by the local model after indexing; null until then or if it failed */
  summary: string | null;
  concepts: string[] | null;
  enrich_status: EnrichStatus;
  enrich_error: string | null;
```

Then add:

```ts
export type EnrichStatus = "pending" | "ok" | "error" | "skipped";

export type EnrichmentStatus = {
  state: "running" | "waiting" | "paused" | "idle" | "waiting for Ollama" | "off";
  current: string | null;
  last_error: string | null;
  paused: boolean;
  enabled: boolean;
  counts: { ok: number; error: number; pending: number; skipped: number };
};
```

Add `enrichment: EnrichmentStatus | null;` to `AdminStatus`. Add `summary_errors: { id: number; path: string; title: string; course: string | null; error: string | null }[];` to `AdminLibrary`. Change the `sendJSON` signature to `method: "POST" | "PUT" | "PATCH" | "DELETE"`.

- [ ] **Step 2: The summary block** (`frontend/components/DocSummary.tsx`)

```tsx
import type { DocumentRow } from "@/lib/api";

type Summarised = Pick<DocumentRow, "summary" | "concepts" | "enrich_status" | "enrich_error">;

/** The reader's "what this file covers": generated summary and key concepts, labelled as generated. */
export function DocSummary({ doc }: { doc: Summarised }) {
  if (doc.enrich_status === "skipped") return null;
  if (doc.enrich_status === "error")
    return <p className="muted doc-summary-note">No summary: {doc.enrich_error ?? "the model's reply wasn't usable"}.</p>;
  if (!doc.summary) return <p className="muted doc-summary-note">Summarising… it appears here within a few minutes.</p>;
  return (
    <section className="doc-summary" aria-label="What this file covers">
      <p dir="auto">
        {doc.summary}
        <span className="gen-tag" title="Written by the local model from this file; it can be wrong">
          generated
        </span>
      </p>
      {doc.concepts && doc.concepts.length > 0 && (
        <ul className="concepts" aria-label="Key concepts">
          {doc.concepts.map((c) => (
            <li key={c} dir="auto">
              {c}
            </li>
          ))}
        </ul>
      )}
      {doc.enrich_status === "pending" && <p className="muted">The file changed; a new summary is on its way.</p>}
    </section>
  );
}
```

In `frontend/app/documents/[id]/page.tsx`, import it and render `<DocSummary doc={doc} />` directly after the `<p className="reader-meta">…</p>` element.

- [ ] **Step 3: The library row** (`frontend/app/documents/page.tsx`)

Replace the `rows` filter's search text with:

```tsx
    (d) =>
      (drawer === null || d.course === drawer) &&
      (!q || `${d.title} ${d.path} ${d.summary ?? ""} ${(d.concepts ?? []).join(" ")}`.toLowerCase().includes(q)),
```

Change the search placeholder to `"Filter by title, folder or topic"`. In the title cell, after the `problem-note` block, add:

```tsx
                    {d.status === "ok" && d.summary && (
                      <span className="summary-line" dir="auto" title={d.summary}>
                        {d.summary}
                      </span>
                    )}
                    {d.enrich_status === "pending" && !d.summary && <span className="enrich-note">summarising…</span>}
                    {d.enrich_status === "error" && (
                      <span className="enrich-note" title={d.enrich_error ?? undefined}>
                        no summary
                      </span>
                    )}
```

- [ ] **Step 4: Styles** (`frontend/app/globals.css`, after `.ocr-tag`)

```css
/* ---- generated summaries -------------------------------------------------------------- */
.summary-line {
  flex-basis: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 0.82rem;
  color: var(--muted);
}

.enrich-note {
  font-size: 0.72rem;
  color: var(--muted);
  font-style: italic;
}

.doc-summary {
  margin-top: 0.8rem;
  max-width: var(--measure);
}

.doc-summary p {
  margin: 0;
  line-height: 1.55;
}

.gen-tag {
  margin-inline-start: 0.4rem;
  padding: 0 0.3rem;
  border: 1px solid currentColor;
  border-radius: 2px;
  font-family: var(--type);
  font-size: 0.7rem;
  font-weight: 700;
  opacity: 0.6;
  vertical-align: 0.1em;
}

.concepts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.9rem;
  margin: 0.5rem 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.85rem;
  color: var(--muted);
}

.concepts li::before {
  content: "· ";
}

.doc-summary-note {
  margin-top: 0.6rem;
  font-size: 0.85rem;
}
```

- [ ] **Step 5: Status card line** (`frontend/components/admin/StatusCard.tsx`)

Add state `const [enrichBusy, setEnrichBusy] = useState(false);` and this helper, next to `backUpNow`:

```tsx
  async function toggleEnrich(pause: boolean) {
    setEnrichBusy(true);
    try {
      const e = await postJSON<EnrichmentStatus>(`/admin/enrich/${pause ? "pause" : "resume"}`, {});
      setS((prev) => (prev ? { ...prev, enrichment: e } : prev));
    } finally {
      setEnrichBusy(false);
    }
  }
```

Import `EnrichmentStatus` from `@/lib/api`. Add the following before `<dt>Backup</dt>`:

```tsx
        <dt>Summaries</dt>
        <dd>
          {!s.enrichment ? (
            "–"
          ) : (
            <>
              <span>
                {(() => {
                  const e = s.enrichment;
                  const c = e.counts;
                  const done = `${c.ok}/${c.ok + c.error + c.pending} summarised`;
                  const extra = [c.error ? `${c.error} failed` : "", c.pending ? `${c.pending} to go` : ""].filter(Boolean);
                  const state =
                    e.state === "running" && e.current ? `summarising ${e.current}` :
                    e.state === "waiting" ? "waiting for a question or index job to finish" : e.state;
                  return [done, ...extra, state].join(" · ");
                })()}
              </span>
              {s.enrichment.enabled && (
                <button
                  type="button"
                  className="quiet-btn"
                  onClick={() => toggleEnrich(!s.enrichment!.paused)}
                  disabled={enrichBusy}
                >
                  {s.enrichment.paused ? "Resume" : "Pause"}
                </button>
              )}
            </>
          )}
        </dd>
```

- [ ] **Step 6: Library admin** (`frontend/components/admin/LibraryAdmin.tsx`)

Add this helper next to `reindex`:

```tsx
  const reenrich = (key: string, body: { course: string } | { document_id: number }) =>
    act(key, async () => {
      const r = await postJSON<{ queued: number }>("/admin/enrich/rerun", body);
      return `Queued ${r.queued} file${r.queued === 1 ? "" : "s"} for new summaries.`;
    });
```

In the module row actions, after the Re-index button, add:

```tsx
                    {m.course && btn(`e:${m.course}`, "Re-enrich", () => reenrich(`e:${m.course}`, { course: m.course! }))}
                    {inline(`e:${m.course}`)}
```

After the "Problem files" block, add:

```tsx
      <h3>Couldn&apos;t summarise</h3>
      {lib.summary_errors.length === 0 ? (
        <p className="muted">Every summarised file has a summary.</p>
      ) : (
        <ul className="admin-list">
          {lib.summary_errors.map((p) => (
            <li key={p.id}>
              <span className="admin-item">
                <strong dir="auto">{p.title}</strong>
                <span className="callno">{p.path}</span>
                <span className="muted">{p.error ?? "The model's reply wasn't usable"}</span>
              </span>
              <span className="row-actions">
                {inline(`s:${p.id}`)}
                {btn(`s:${p.id}`, "Re-enrich", () => reenrich(`s:${p.id}`, { document_id: p.id }))}
              </span>
            </li>
          ))}
        </ul>
      )}
```

- [ ] **Step 7: Type-check and lint**

Run: `npx tsc --noEmit` and `npm run lint` (in `frontend/`)
Expected: no errors.

- [ ] **Step 8: Verify in the browser, with a real backfill**

1. Start the backend (`uv run uvicorn app.main:app --port 8000` in `backend/`) and the frontend dev server with `preview_start`. If `.claude/launch.json` lacks a frontend entry, add `{"name": "frontend", "runtimeExecutable": "npm", "runtimeArgs": ["run", "dev"], "port": 3000}`.
2. On `/admin`, the Status card shows "Summaries 0/N summarised · N to go · summarising <title>". Pause and Resume toggle.
3. Ask a question on the desk while it runs. The status reads "waiting…" during the answer, and the answer time is unchanged: compare the latency with a paused run.
4. After a few files, open `/documents`. Summaries show as single lines, pending files say "summarising…", and searching for a concept word filters rows.
5. Open a summarised file in the reader. The summary is marked "generated", with the concepts below it.
6. Let the backfill finish. Record the wall time and the count of errors. Read 5 summaries across FR and EN modules and note any that are wrong or in the wrong language. Keep this for the README.
7. Take a screenshot of the library and the reader header as proof.

- [ ] **Step 9: README** (add under "Admin panel", as a new section "Summaries and concepts")

```markdown
## Summaries and concepts

After a file is indexed, a background job has the local model write a short summary and 5–10 key concepts for it:
- **Library:** the summary shows as one line under each file, and the filter box also searches summaries and concepts.
- **Reader:** the full summary and concepts sit at the top, marked **generated** because a 4B model can get them wrong.
- **Timing:** the job pauses while you're asking a question and during rescans, re-indexes and evaluation runs, so answers aren't slowed. Long files are summarised in parts, then combined. The first pass over the library took <N> minutes. After that, only new and changed files are summarised.
- **Admin:**
  - the Status card shows progress, with **Pause** and **Resume**;
  - Library has **Re-enrich** per module, and lists the files that couldn't be summarised.
- **Turning it off:** set `enrich_enabled: false` in `config.yaml`.
```

Fill in `<N>` from Step 8.

- [ ] **Step 10: Commit**

```bash
git add frontend/ README.md
git commit -m "Summaries in the library, reader and admin: one-line summaries, concepts, progress, pause and re-enrich"
```

---

## Stage 2: the tag vocabulary

### Task 6: Vocabulary pass, tag operations, backups

**Files:**
- Create: `backend/app/enrich/vocab.py`
- Modify:
  - `backend/app/enrich/worker.py` (`_after_write`)
  - `backend/app/admin/backup.py` (tables, sequences, tolerant restore)
- Test: `backend/tests/test_enrich.py` (append), `backend/tests/test_backup.py` (tags round-trip)

**Interfaces:**
- Consumes: `ollama.embed`, `get_settings().tag_merge_threshold`
- Produces:
  - `vocab.normalise(name: str) -> str`
  - `vocab.relink(conn, course: str | None) -> None`
  - `vocab.run(course: str | None, embed=None) -> dict` with `{new_raw, new_tags, removed}`
  - `vocab.list_tags(course: str | None = None, all_courses: bool = True) -> list[dict]`, each `{id, course, name, count, raws, user_named}`
  - `vocab.document_tags(doc_id: int) -> list[dict]`, each `{id, name}`
  - `vocab.rename(tag_id: int, name: str) -> dict | None` (raises `Clash`)
  - `vocab.merge(src: int, into: int) -> dict | None` (raises `ValueError` across modules)
  - `vocab.delete(tag_id: int) -> bool`
  - `class Clash(ValueError)`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_enrich.py`)

```python
def axis_embed(groups):
    """Embedder where every string in the same group gets the same unit vector (cosine 1), others are orthogonal."""
    index = {s: i for i, g in enumerate(groups) for s in g}

    def embed(texts):
        out = []
        for t in texts:
            v = np.zeros(1024, dtype=np.float32)
            v[index.setdefault(t, len(index))] = 1.0  # an unknown string gets its own axis, stable within the test
            out.append(v)
        return out
    return embed


def tagged(db, path, raw_tags, course="Course0"):
    doc_id = add_doc(db, path, course=course)
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE documents SET raw_tags = %s, enriched_sha = sha256, enrich_status = 'ok' WHERE id = %s",
                     (Jsonb(raw_tags), doc_id))
    return doc_id


def names(course="Course0"):
    from app.enrich.vocab import list_tags

    return {t["name"]: t["count"] for t in list_tags(course, all_courses=False)}


EMBED = axis_embed([["kubernetes", "k8s", "container orchestration"], ["docker"], ["ci/cd", "continuous integration"]])


def test_vocabulary_merges_near_duplicates_under_the_most_frequent_form(env):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["kubernetes", "ci/cd"])
    tagged(db, "Course0/c.md", ["k8s", "continuous integration"])
    r = vocab.run("Course0", embed=EMBED)
    assert r["new_raw"] == 5 and r["new_tags"] == 3
    assert names() == {"kubernetes": 3, "docker": 1, "ci/cd": 2}
    assert sorted(t["name"] for t in vocab.document_tags(a)) == ["docker", "kubernetes"]
    assert vocab.run("Course0", embed=EMBED) == {"new_raw": 0, "new_tags": 0, "removed": 0}  # idempotent


def test_new_raw_tags_join_existing_tags_and_modules_stay_separate(env):
    from app.enrich import vocab

    _, db = env
    tagged(db, "Course0/a.md", ["kubernetes"])
    vocab.run("Course0", embed=EMBED)
    tagged(db, "Course0/b.md", ["container orchestration"])
    tagged(db, "Course1/c.md", ["kubernetes"], course="Course1")
    vocab.run("Course0", embed=EMBED)
    vocab.run("Course1", embed=EMBED)
    assert names() == {"kubernetes": 2}
    assert names("Course1") == {"kubernetes": 1}


def test_rename_merge_delete_survive_later_passes(env):
    from app.enrich import vocab

    _, db = env
    tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["ci/cd"])
    vocab.run("Course0", embed=EMBED)
    ids = {t["name"]: t["id"] for t in vocab.list_tags("Course0", all_courses=False)}

    assert vocab.rename(ids["kubernetes"], "  Kubernetes (K8s) ")["name"] == "kubernetes (k8s)"
    with pytest.raises(vocab.Clash):
        vocab.rename(ids["docker"], "kubernetes (k8s)")
    vocab.merge(ids["docker"], ids["kubernetes"])
    assert vocab.delete(ids["ci/cd"]) is True

    tagged(db, "Course0/c.md", ["docker", "ci/cd"])  # raw forms you merged away and deleted
    vocab.run("Course0", embed=EMBED)
    assert names() == {"kubernetes (k8s)": 2}


def test_unused_tags_are_removed_unless_you_named_them(env):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["docker"])
    b = tagged(db, "Course0/b.md", ["ci/cd"])
    vocab.run("Course0", embed=EMBED)
    vocab.rename(next(t["id"] for t in vocab.list_tags("Course0", all_courses=False) if t["name"] == "ci/cd"), "ci")
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = ANY(%s)", ([a, b],))
    assert vocab.run("Course0", embed=EMBED)["removed"] == 1
    assert names() == {"ci": 0}


def test_worker_links_known_tags_at_once_and_runs_the_pass_when_the_module_is_done(env):
    from app.enrich.worker import Enricher

    _, db = env
    add_doc(db, "Course0/a.md")
    add_doc(db, "Course0/b.md")
    e = Enricher(chat=good_chat, embed=EMBED)
    e.step()
    assert names() == {}  # b is still pending: no pass yet
    e.step()
    assert names() == {"optimization": 2, "stochastic gd": 2}
```

In `backend/tests/test_backup.py`, add:

```python
def test_tags_and_aliases_round_trip(env, tmp_path):
    from app.admin import backup

    _, db = env
    with db.get_pool().connection() as conn:
        t = conn.execute("INSERT INTO tags (course, name, user_named) VALUES ('C', 'kubernetes', true) RETURNING id").fetchone()["id"]
        conn.execute("INSERT INTO tag_aliases (course, raw, tag_id) VALUES ('C', 'k8s', %s), ('C', 'junk', NULL)", (t,))
    f = backup.backup(tmp_path)
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM tag_aliases")
    r = backup.restore(f)
    assert (r["tags"], r["tag_aliases"]) == (1, 2)

    with db.get_pool().connection() as conn:  # a tag recreated under another id: its alias is skipped, not fatal
        conn.execute("DELETE FROM tag_aliases")
        conn.execute("DELETE FROM tags")
        conn.execute("INSERT INTO tags (course, name) VALUES ('C', 'kubernetes')")
    r = backup.restore(f)
    assert (r["tags"], r["tag_aliases"]) == (0, 1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py tests/test_backup.py -v`
Expected: the new tests FAIL. `app.enrich.vocab` is missing, and the backup has no `tags` table.

- [ ] **Step 3: Implement** (`backend/app/enrich/vocab.py`)

```python
"""Per-module tag vocabulary. The model proposes raw tags per file; each pass maps new raw tags onto canonical
tags by bge-m3 similarity (tag_aliases), then rebuilds document_tags. Your renames, merges and deletes are
aliases and user_named flags, so later passes keep them.
"""

from collections import Counter

import numpy as np

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama

MAX_NAME = 40
_IN_COURSE = "course IS NOT DISTINCT FROM %(c)s::text"


class Clash(ValueError):
    pass


def normalise(name: str) -> str:
    return " ".join(name.lower().split())


def relink(conn, course: str | None) -> None:
    """document_tags for the module, from each document's raw tags and the aliases."""
    conn.execute(
        """DELETE FROM document_tags dt USING documents d
           WHERE dt.document_id = d.id AND d.course IS NOT DISTINCT FROM %(c)s::text""", {"c": course})
    conn.execute(
        """INSERT INTO document_tags (document_id, tag_id)
           SELECT DISTINCT d.id, a.tag_id
           FROM documents d
           CROSS JOIN LATERAL jsonb_array_elements_text(d.raw_tags) AS r(raw)
           JOIN tag_aliases a ON a.raw = r.raw AND a.course IS NOT DISTINCT FROM d.course
           WHERE d.course IS NOT DISTINCT FROM %(c)s::text AND d.enrich_status = 'ok' AND a.tag_id IS NOT NULL""",
        {"c": course})


def run(course: str | None, embed=None) -> dict:
    embed = embed or ollama.embed
    threshold = get_settings().tag_merge_threshold
    with get_pool().connection() as conn, conn.transaction():
        freq: Counter = Counter()
        for r in conn.execute(
            f"SELECT raw_tags FROM documents WHERE {_IN_COURSE} AND enrich_status = 'ok' AND raw_tags IS NOT NULL",
            {"c": course},
        ):
            freq.update(set(r["raw_tags"]))
        aliased = {r["raw"] for r in conn.execute(f"SELECT raw FROM tag_aliases WHERE {_IN_COURSE}", {"c": course})}
        new = sorted((t for t in freq if t not in aliased), key=lambda t: (-freq[t], t))
        created = 0
        if new:
            tags = conn.execute(f"SELECT id, name FROM tags WHERE {_IN_COURSE} ORDER BY id", {"c": course}).fetchall()
            vectors = embed([t["name"] for t in tags] + new)
            known = [(t["id"], np.asarray(v)) for t, v in zip(tags, vectors[: len(tags)], strict=True)]
            for raw, v in zip(new, vectors[len(tags):], strict=True):
                v = np.asarray(v)
                best = max(known, key=lambda k: float(np.dot(k[1], v)), default=None)
                if best is not None and float(np.dot(best[1], v)) >= threshold:
                    tag_id = best[0]
                else:
                    row = conn.execute(
                        "INSERT INTO tags (course, name) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
                        (course, raw)).fetchone()
                    tag_id = row["id"] if row else conn.execute(
                        f"SELECT id FROM tags WHERE {_IN_COURSE} AND name = %(n)s", {"c": course, "n": raw}
                    ).fetchone()["id"]
                    created += 1 if row else 0
                    known.append((tag_id, v))
                conn.execute("INSERT INTO tag_aliases (course, raw, tag_id) VALUES (%s, %s, %s)", (course, raw, tag_id))
        relink(conn, course)
        removed = conn.execute(
            f"""DELETE FROM tags t WHERE {_IN_COURSE} AND NOT user_named
                AND NOT EXISTS (SELECT 1 FROM document_tags dt WHERE dt.tag_id = t.id)""", {"c": course}
        ).rowcount
    return {"new_raw": len(new), "new_tags": created, "removed": removed}


def list_tags(course: str | None = None, all_courses: bool = True) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            f"""SELECT t.id, t.course, t.name, t.user_named,
                       (SELECT count(*) FROM document_tags dt WHERE dt.tag_id = t.id) AS count,
                       COALESCE((SELECT jsonb_agg(a.raw ORDER BY a.raw) FROM tag_aliases a
                                 WHERE a.tag_id = t.id AND a.raw <> t.name), '[]') AS raws
                FROM tags t WHERE %(all)s OR t.{_IN_COURSE}
                ORDER BY t.course NULLS LAST, count DESC, t.name""",
            {"all": all_courses, "c": course},
        ).fetchall()


def document_tags(doc_id: int) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            """SELECT t.id, t.name FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
               WHERE dt.document_id = %s ORDER BY t.name""", (doc_id,)).fetchall()


def _tag(conn, tag_id: int) -> dict | None:
    return conn.execute("SELECT id, course, name FROM tags WHERE id = %s", (tag_id,)).fetchone()


def rename(tag_id: int, name: str) -> dict | None:
    name = normalise(name)
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"a tag name is 1 to {MAX_NAME} characters")
    with get_pool().connection() as conn, conn.transaction():
        tag = _tag(conn, tag_id)
        if tag is None:
            return None
        clash = conn.execute(f"SELECT 1 FROM tags WHERE {_IN_COURSE} AND name = %(n)s AND id <> %(id)s",
                             {"c": tag["course"], "n": name, "id": tag_id}).fetchone()
        if clash:
            raise Clash(f"this module already has a tag called {name}; merge them instead")
        return conn.execute("UPDATE tags SET name = %s, user_named = true WHERE id = %s RETURNING id, course, name",
                            (name, tag_id)).fetchone()


def merge(src: int, into: int) -> dict | None:
    with get_pool().connection() as conn, conn.transaction():
        a, b = _tag(conn, src), _tag(conn, into)
        if a is None or b is None or src == into:
            return None
        if a["course"] != b["course"]:
            raise ValueError("tags from different modules can't be merged")
        conn.execute("UPDATE tag_aliases SET tag_id = %s WHERE tag_id = %s", (into, src))
        conn.execute("UPDATE tags SET user_named = true WHERE id = %s", (into,))
        conn.execute("DELETE FROM tags WHERE id = %s", (src,))
        relink(conn, b["course"])
        return b


def delete(tag_id: int) -> bool:
    with get_pool().connection() as conn, conn.transaction():
        conn.execute("UPDATE tag_aliases SET tag_id = NULL WHERE tag_id = %s", (tag_id,))  # the raw forms stay dropped
        return conn.execute("DELETE FROM tags WHERE id = %s", (tag_id,)).rowcount > 0
```

- [ ] **Step 4: Hook tags into the worker** (`backend/app/enrich/worker.py`)

Add `from . import vocab` to the imports, and replace `_after_write` with:

```python
    def _after_write(self, doc: dict, ok: bool) -> None:
        """Link raw tags that already have an alias; run the vocabulary pass once the module has no pending files."""
        with get_pool().connection() as conn, conn.transaction():
            vocab.relink(conn, doc["course"])
            pending = conn.execute(
                f"SELECT 1 FROM documents WHERE {PENDING} AND course IS NOT DISTINCT FROM %s::text LIMIT 1",
                (doc["course"],)).fetchone()
        if pending is None:
            vocab.run(doc["course"], embed=self.embed)
```

- [ ] **Step 5: Back up tags** (`backend/app/admin/backup.py`)

- Update the module docstring to say "…, the evaluation set and its runs, and your tag vocabulary."
- Add `"tags": ("id", set())` and `"tag_aliases": ("id", set())` to `TABLES`, after `eval_runs`. The order matters: tags must be restored before the aliases that point to them.
- Change `SEQUENCES` to `("query_log", "eval_questions", "eval_runs", "tags", "tag_aliases")`.
- In `restore()`, add `import psycopg` at the top of the file, and replace the insert statement with:

```python
            try:
                with conn.transaction():  # a savepoint: one row that can't go back doesn't sink the restore
                    inserted[table] += conn.execute(
                        f"INSERT INTO {table} ({cols}) VALUES ({params}) ON CONFLICT DO NOTHING", values
                    ).rowcount
            except psycopg.errors.ForeignKeyViolation:
                log.warning("restore: skipped a %s row whose parent isn't there", table)
```

The target was dropped from `ON CONFLICT`, so a clash on any unique key (a tag's module and name) is skipped too. `key` is still used for `ORDER BY` in `backup()`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_enrich.py tests/test_backup.py -v`, then `uv run pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/enrich/vocab.py backend/app/enrich/worker.py backend/app/admin/backup.py backend/tests/
git commit -m "Tags: per-module vocabulary merged by similarity, rename/merge/delete that stick, tags in the backup"
```

---

### Task 7: Tag API

**Files:**
- Modify: `backend/app/api/routes.py` (`GET /tags`; tags on documents), `backend/app/api/admin.py` (tag operations)
- Test: `backend/tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `vocab.*` from Task 6
- Produces:
  - `GET /documents` rows and `GET /documents/{id}/pages` gain `tags: [{id, name}]`
  - `GET /tags?course=` returns `[{id, course, name, count, raws, user_named}]`. Without `course` it returns every module.
  - `PATCH /admin/tags/{id}` with `{name}` returns the tag, or 404, 409 or 422
  - `POST /admin/tags/merge` with `{from_id, into}` returns the tag, or 404 or 400
  - `DELETE /admin/tags/{id}` returns 204 or 404
  - `POST /admin/tags/vocab` with `{course}` returns the pass result

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_tag_routes(env, monkeypatch, tmp_path):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["docker"])
    vocab.run("Course0", embed=EMBED)
    c = client(monkeypatch, tmp_path)

    tags = c.get("/tags", params={"course": "Course0"}).json()
    assert [(t["name"], t["count"]) for t in tags] == [("docker", 2), ("kubernetes", 1)]
    ids = {t["name"]: t["id"] for t in tags}
    doc_row = next(r for r in c.get("/documents").json() if r["id"] == a)
    assert [t["name"] for t in doc_row["tags"]] == ["docker", "kubernetes"]

    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": "Kubernetes"}).status_code == 409
    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": ""}).status_code == 422
    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": "Containers"}).json()["name"] == "containers"
    assert c.post("/admin/tags/merge", json={"from_id": ids["kubernetes"], "into": ids["docker"]}).status_code == 200
    assert [t["name"] for t in c.get("/tags", params={"course": "Course0"}).json()] == ["containers"]
    assert c.delete(f"/admin/tags/{ids['docker']}").status_code == 204
    assert c.delete(f"/admin/tags/{ids['docker']}").status_code == 404
    monkeypatch.setattr(vocab.ollama, "embed", EMBED)
    assert c.post("/admin/tags/vocab", json={"course": "Course0"}).json()["new_raw"] == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_enrich.py::test_tag_routes -v`
Expected: FAIL with a 404 on `/tags`.

- [ ] **Step 3: Add the public routes** (`backend/app/api/routes.py`)

Add `from ..enrich import vocab` to the imports. In the `documents()` SELECT list, add:

```sql
                      COALESCE((SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name) ORDER BY t.name)
                                FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
                                WHERE dt.document_id = d.id), '[]') AS tags
```

In `document_pages()`, add `"tags": vocab.document_tags(doc_id),` to the returned dict. Then add:

```python
@router.get("/tags")
def tags(course: str | None = None) -> list[dict]:
    return vocab.list_tags(course, all_courses=course is None)
```

- [ ] **Step 4: Add the admin routes** (`backend/app/api/admin.py`)

Add `from ..enrich import vocab` to the imports, then:

```python
class TagName(BaseModel):
    name: str


class MergeBody(BaseModel):
    from_id: int
    into: int


class CourseBody(BaseModel):
    course: str | None = None


@router.patch("/tags/{tag_id}")
def tag_rename(tag_id: int, body: TagName) -> dict:
    try:
        tag = vocab.rename(tag_id, body.name)
    except vocab.Clash as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if tag is None:
        raise HTTPException(404, "no such tag")
    return tag


@router.post("/tags/merge")
def tag_merge(body: MergeBody) -> dict:
    try:
        tag = vocab.merge(body.from_id, body.into)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if tag is None:
        raise HTTPException(404, "no such tags, or the same tag twice")
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def tag_delete(tag_id: int) -> Response:
    if not vocab.delete(tag_id):
        raise HTTPException(404, "no such tag")
    return Response(status_code=204)


@router.post("/tags/vocab")
def tag_vocab(body: CourseBody) -> dict:
    return vocab.run(body.course)
```

Also add `Response` to the `fastapi` import.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/app/api/admin.py backend/tests/test_enrich.py
git commit -m "Tags API: tags on documents, list per module, rename, merge, delete and run the vocabulary pass"
```

---

### Task 8: Tags in the library, reader and admin

**Files:**
- Create: `frontend/components/admin/TagsCard.tsx`
- Modify:
  - `frontend/lib/api.ts`
  - `frontend/app/documents/page.tsx`
  - `frontend/components/DocSummary.tsx`
  - `frontend/app/documents/[id]/page.tsx`
  - `frontend/app/admin/page.tsx`
  - `frontend/app/globals.css`
  - `README.md`

**Interfaces:**
- Consumes: the Task 7 API
- Produces:
  - the TS type `Tag = { id: number; name: string }`, and `TagRow`
  - `DocumentRow.tags: Tag[]`
  - library URL params: `?m=<module>&tag=<id>&tag=<id>` (AND)

- [ ] **Step 1: Types** (`frontend/lib/api.ts`)

```ts
export type Tag = { id: number; name: string };
export type TagRow = Tag & { course: string | null; count: number; raws: string[]; user_named: boolean };
```

Add `tags: Tag[];` to `DocumentRow`.

- [ ] **Step 2: Tag bar and filter** (`frontend/app/documents/page.tsx`)

Import `useRouter, useSearchParams` from `next/navigation` and `type Tag` from `@/lib/api`. Inside `DrawerView`, add:

```tsx
  const params = useSearchParams();
  const router = useRouter();
  const picked = params.getAll("tag").map(Number).filter(Number.isFinite);
  const setPicked = (ids: number[]) => {
    const next = new URLSearchParams(params);
    next.delete("tag");
    ids.forEach((id) => next.append("tag", String(id)));
    const qs = next.toString();
    router.replace(`/documents${qs ? `?${qs}` : ""}`, { scroll: false });
  };
```

Extend the `rows` filter with `&& picked.every((id) => d.tags.some((t) => t.id === id))`. Compute the drawer's tags, by count:

```tsx
  const tagCounts = new Map<number, { tag: Tag; course: string | null; n: number }>();
  for (const d of total)
    for (const t of d.tags) {
      const e = tagCounts.get(t.id) ?? { tag: t, course: d.course, n: 0 };
      e.n += 1;
      tagCounts.set(t.id, e);
    }
  const tagList = [...tagCounts.values()].sort((a, b) => b.n - a.n || a.tag.name.localeCompare(b.tag.name));
```

Render this between the header and the notices:

```tsx
      {tagList.length > 0 && (
        <nav className="tag-bar" aria-label="Filter by topic">
          {drawer === null
            ? [...new Set(tagList.map((t) => t.course ?? "Loose notes"))].map((course) => (
                <div key={course} className="tag-group">
                  <span className="tag-group-name">{course}</span>
                  {tagList.filter((t) => (t.course ?? "Loose notes") === course).map(chip)}
                </div>
              ))
            : tagList.map(chip)}
          {picked.length > 0 && (
            <button type="button" className="quiet-btn" onClick={() => setPicked([])}>
              Clear topics
            </button>
          )}
        </nav>
      )}
```

Define `chip` above the return:

```tsx
  const chip = ({ tag, n }: { tag: Tag; n: number }) => {
    const on = picked.includes(tag.id);
    return (
      <button
        key={tag.id}
        type="button"
        className={`tag-chip${on ? " on" : ""}`}
        aria-pressed={on}
        onClick={() => setPicked(on ? picked.filter((id) => id !== tag.id) : [...picked, tag.id])}
        dir="auto"
      >
        {tag.name} <span className="tag-count">{n}</span>
      </button>
    );
  };
```

Change the "no match" notice to: `No fiche matches {query ? \`“${query}”\` : "these topics"}.` A picked tag that isn't in this drawer never matches. `useDrawer()` preserves `tag`, and the rail's drawer links drop it, which is fine.

- [ ] **Step 3: Tags in the reader** (`frontend/components/DocSummary.tsx`)

Extend `Summarised` with `"tags" | "course"`. Import `Link` from `next/link` and `drawerHref` from `@/lib/useLibrary`. After the concepts list, add:

```tsx
      {doc.tags.length > 0 && (
        <p className="doc-tags">
          {doc.tags.map((t) => (
            <Link
              key={t.id}
              className="tag-chip"
              href={`${drawerHref("/documents", doc.course)}${doc.course ? "&" : "?"}tag=${t.id}`}
              dir="auto"
            >
              {t.name}
            </Link>
          ))}
        </p>
      )}
```

`DocumentPages` already gets `tags` through `Omit<DocumentRow, "chunk_count">`, and the backend returns it (Task 7).

- [ ] **Step 4: Styles** (`frontend/app/globals.css`)

```css
.tag-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin: 0.9rem 0 0.2rem;
}

.tag-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  flex-basis: 100%;
}

.tag-group-name {
  font-size: 0.75rem;
  color: var(--muted);
  min-width: 9rem;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.12rem 0.5rem;
  border: 1px solid var(--rule-blue);
  border-radius: 999px;
  background: var(--card);
  color: var(--ink);
  font: inherit;
  font-size: 0.8rem;
  text-decoration: none;
  cursor: pointer;
}

.tag-chip:hover {
  border-color: var(--primary);
}

.tag-chip.on {
  background: var(--sel);
  border-color: var(--primary);
}

.tag-count {
  font-size: 0.7rem;
  color: var(--muted);
}

.doc-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 0.6rem 0 0;
}
```

- [ ] **Step 5: The admin Tags card** (`frontend/components/admin/TagsCard.tsx`)

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getJSON, postJSON, sendJSON, type TagRow } from "@/lib/api";

/** Per-module tag vocabulary: rename, merge two, delete, or run the merge pass now. */
export function TagsCard() {
  const [courses, setCourses] = useState<string[]>([]);
  const [course, setCourse] = useState<string>("");
  const [tags, setTags] = useState<TagRow[] | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  useEffect(() => {
    getJSON<string[]>("/courses").then((c) => {
      setCourses(c);
      setCourse((prev) => prev || c[0] || "");
    });
  }, []);
  const load = useCallback(() => {
    if (!course) return;
    getJSON<TagRow[]>(`/tags?course=${encodeURIComponent(course)}`).then(setTags);
    setPicked([]);
  }, [course]);
  useEffect(load, [load]);

  async function act(fn: () => Promise<string>) {
    setNote(null);
    try {
      setNote({ text: await fn() });
    } catch (e) {
      setNote({ text: e instanceof ApiError ? e.message : "That didn't work.", bad: true });
    }
    load();
  }

  const byId = new Map((tags ?? []).map((t) => [t.id, t]));
  return (
    <section className="admin-card" aria-labelledby="tags-h">
      <header className="admin-card-head">
        <h2 id="tags-h">Tags</h2>
        <span className="admin-actions">
          <select value={course} onChange={(e) => setCourse(e.target.value)} aria-label="Module">
            {courses.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <button
            type="button"
            className="quiet-btn"
            disabled={picked.length !== 2}
            onClick={() => {
              const [a, b] = picked.map((id) => byId.get(id)!);
              const [from, into] = a.count > b.count ? [b, a] : [a, b];
              act(async () => {
                await postJSON("/admin/tags/merge", { from_id: from.id, into: into.id });
                return `Merged “${from.name}” into “${into.name}”.`;
              });
            }}
          >
            Merge the two selected
          </button>
          <button
            type="button"
            className="quiet-btn"
            onClick={() =>
              act(async () => {
                const r = await postJSON<{ new_raw: number; new_tags: number; removed: number }>("/admin/tags/vocab", { course });
                return `${r.new_raw} new raw tags, ${r.new_tags} new tags, ${r.removed} unused removed.`;
              })
            }
          >
            Run vocabulary pass
          </button>
        </span>
      </header>
      {note && <p className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</p>}
      {!tags ? (
        <p className="muted">Loading tags…</p>
      ) : tags.length === 0 ? (
        <p className="muted">No tags yet. They appear once this module&apos;s files are summarised.</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">Select</span></th>
              <th scope="col">Tag</th>
              <th scope="col">Files</th>
              <th scope="col">Merged forms</th>
              <th scope="col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {tags.map((t) => (
              <tr key={t.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${t.name}`}
                    checked={picked.includes(t.id)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, t.id].slice(-2) : picked.filter((id) => id !== t.id))}
                  />
                </td>
                <th scope="row" dir="auto">
                  {editing?.id === t.id ? (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const name = editing.name;
                        setEditing(null);
                        act(async () => {
                          await sendJSON("PATCH", `/admin/tags/${t.id}`, { name });
                          return `Renamed to “${name.trim().toLowerCase()}”.`;
                        });
                      }}
                    >
                      <input
                        autoFocus
                        value={editing.name}
                        onChange={(e) => setEditing({ id: t.id, name: e.target.value })}
                        onBlur={() => setEditing(null)}
                        aria-label="New name"
                      />
                    </form>
                  ) : (
                    t.name
                  )}
                </th>
                <td>{t.count}</td>
                <td className="muted">{t.raws.join(", ") || "–"}</td>
                <td>
                  <span className="row-actions">
                    <button type="button" className="quiet-btn" onClick={() => setEditing({ id: t.id, name: t.name })}>
                      Rename
                    </button>
                    <button
                      type="button"
                      className="quiet-btn"
                      onClick={() =>
                        act(async () => {
                          await sendJSON("DELETE", `/admin/tags/${t.id}`, {});
                          return `Deleted “${t.name}”. It won't come back on later passes.`;
                        })
                      }
                    >
                      Delete
                    </button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

Render `<TagsCard />` in `frontend/app/admin/page.tsx`, right after `<LibraryAdmin />`, and import it.

- [ ] **Step 6: Type-check and lint**

Run: `npx tsc --noEmit` and `npm run lint`
Expected: no errors.

- [ ] **Step 7: Tune the threshold on real tags, then verify in the browser**

1. With the backend running after the Stage 1 backfill, press "Run vocabulary pass" for each module in admin Tags. The worker also runs it by itself once a module has no pending files.
2. Read the DEVOPS and Probability 2 tag tables:
   - If near-duplicates survive (e.g. "docker" and "docker containers" as separate tags), the threshold is too high.
   - If unrelated tags share a row (the "Merged forms" column shows wrong forms), it's too low.
3. To try another value, remove the module's tags:

   ```bash
   docker compose exec postgres psql -U secondbrain -c "DELETE FROM tags WHERE course='DEVOPS'; DELETE FROM tag_aliases WHERE course='DEVOPS'"
   ```

   Then set `tag_merge_threshold` in `config.yaml` to 0.80 or 0.90, restart the backend and rerun the pass. Keep the value that reads best, and record it in `config.yaml` with a one-line comment.
4. Check the library:
   - the tag bar shows the drawer's tags;
   - clicking two narrows the list, and the URL gains `&tag=…&tag=…`;
   - "Clear topics" resets;
   - with no drawer open, tags are grouped by module.
5. In the reader, the tag chips link to the filtered library.
6. In admin, rename a tag, merge two, delete one, run the pass again, and confirm all three edits stick.
7. Take a screenshot of the filtered library and the Tags card.

- [ ] **Step 8: README** (extend "Summaries and concepts", renamed "Summaries, concepts and tags")

```markdown
- **Tags:** each file also gets 3–8 topic tags:
  - Similar tags in a module are merged into one (e.g. "k8s" and "kubernetes"), by bge-m3 similarity at `tag_merge_threshold` (<value>).
  - The library's tag bar filters by topic. Picking more than one narrows the list further.
  - Tags in the reader link to that filter.
- **Admin Tags:**
  - rename, merge two, or delete a tag, per module;
  - your edits are remembered, so a deleted tag doesn't come back and merged forms stay merged;
  - tags and your edits are in the daily backup; summaries aren't, because they can be regenerated.
```

- [ ] **Step 9: Commit**

```bash
git add frontend/ README.md config.yaml
git commit -m "Tags in the library, reader and admin: topic filter bar, reader tag links, vocabulary editing"
```

---

## Stage 3: the retrieval experiment

### Task 9: `doc_boost` and `doc_context`

**Files:**
- Modify:
  - `backend/app/enrich/worker.py` (summary embedding and its backfill)
  - `backend/app/rag/retrieve.py` (`_COLUMNS`, `_dense`)
  - `backend/app/llm/prompts.py` (`format_context`)
  - `backend/app/admin/settings.py` (two `EDITABLE` fields)
  - `backend/app/eval/run.py` (params)
- Test: `backend/tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `documents.summary_embedding`; settings `doc_boost` and `doc_context`
- Produces:
  - `prompts.first_sentence(text: str) -> str`
  - `Enricher._embed_pending_summaries() -> int`
  - hits gain `summary` and, from dense, `doc_score`

- [ ] **Step 1: Write the failing tests** (append)

```python
def unit(*pairs):
    v = np.zeros(1024, dtype=np.float32)
    for i, x in pairs:
        v[i] = x
    return v / np.linalg.norm(v)


def boost_fixture(db):
    """Chunk A is closer to the question (0.9 vs 0.85), but B's file summary matches the question and A's doesn't."""
    ids = []
    for path, chunk_vec, summary_vec in (("C/a.md", unit((0, 0.9), (1, 0.436)), unit((1, 1.0))),
                                         ("C/b.md", unit((0, 0.85), (2, 0.527)), unit((0, 1.0)))):
        with db.get_pool().connection() as conn:
            d = conn.execute(
                """INSERT INTO documents (path, sha256, course, title, mime, status, summary, summary_embedding)
                   VALUES (%s, 'x', 'C', %s, 'text/markdown', 'ok', 'About it. More.', %s) RETURNING id""",
                (path, path, summary_vec)).fetchone()["id"]
            conn.execute("INSERT INTO chunks (document_id, ord, page, text, n_tokens, embedding) VALUES (%s, 0, 1, 't', 1, %s)",
                         (d, chunk_vec))
        ids.append(d)
    return ids


def test_doc_boost_reorders_by_summary_and_refusal_uses_the_raw_score(env, monkeypatch):
    from app.config import get_settings
    from app.rag.retrieve import retrieve_with_vector

    _, db = env
    a, b = boost_fixture(db)
    q = unit((0, 1.0))
    hits, _ = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [h["doc_id"] for h in hits] == [a, b]  # doc_boost 0: today's order

    monkeypatch.setenv("DOC_BOOST", "0.1")
    get_settings.cache_clear()
    hits, sources = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [h["doc_id"] for h in hits] == [b, a]
    assert round(hits[0]["score"], 2) == 0.85  # the score shown and used for refusal is unchanged
    monkeypatch.setenv("MIN_SCORE", "0.88")
    get_settings.cache_clear()
    _, sources = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [s["doc_id"] for s in sources] == [a]
    get_settings.cache_clear()


def test_doc_context_adds_the_summary_line(monkeypatch):
    from app.config import get_settings
    from app.llm.prompts import first_sentence, format_context

    src = [{"title": "Chap 1", "page": 2, "mime": "application/pdf", "label": None, "text": "Body.",
            "summary": "Covers gradient descent. Also momentum."}]
    assert first_sentence("Covers gradient descent. Also momentum.") == "Covers gradient descent."
    assert "About this file" not in format_context(src)
    monkeypatch.setenv("DOC_CONTEXT", "on")
    get_settings.cache_clear()
    assert "[1] (Chap 1, p. 2)\nAbout this file: Covers gradient descent.\nBody." in format_context(src)
    get_settings.cache_clear()


def test_worker_embeds_summaries_and_backfills_missing_ones(env):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    e = Enricher(chat=good_chat, embed=fake_embed)
    e.step()
    assert doc(db, a)["summary_embedding"] is not None
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE documents SET summary_embedding = NULL")
    assert e.step() is True  # nothing pending: embeds the summary that lacks a vector
    assert doc(db, a)["summary_embedding"] is not None and e.step() is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enrich.py -k "doc_boost or doc_context or embeds" -v`
Expected: FAIL. The order doesn't change, and `first_sentence` and the summary embedding are missing.

- [ ] **Step 3: Retrieval** (`backend/app/rag/retrieve.py`)

Add `d.summary` to `_COLUMNS`:

```python
_COLUMNS = """c.id AS chunk_id, c.document_id AS doc_id, c.page, c.text, c.meta->>'label' AS label,
              (c.meta->>'ocr')::boolean IS TRUE AS ocr,
              d.title, d.course, d.mime, d.path, d.summary, 1 - (c.embedding <=> %(q)s) AS score"""
```

Replace `_dense` with:

```python
def _dense(conn, qvec, k: int, course: str | None) -> list[dict]:
    """Nearest chunks. With doc_boost > 0, candidate_k are fetched and re-sorted by
    score + doc_boost x similarity(question, file summary); `score` itself stays the chunk's cosine."""
    s = get_settings()
    boost = s.doc_boost
    conn.execute("SET hnsw.ef_search = 100")
    hits = conn.execute(
        f"""SELECT {_COLUMNS}, COALESCE(1 - (d.summary_embedding <=> %(q)s), 0) AS doc_score
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {_COURSE}
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s""",
        {"q": qvec, "k": max(k, s.candidate_k) if boost else k, "course": course},
    ).fetchall()
    if boost:
        hits.sort(key=lambda h: -(h["score"] + boost * h["doc_score"]))
        hits = hits[:k]
    return hits
```

- [ ] **Step 4: The prompt** (`backend/app/llm/prompts.py`)

Add `import re` and `from ..config import get_settings`, then:

```python
def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0][:200]


def format_context(sources: list[dict]) -> str:
    """sources: dicts with title, page, mime, label, text (and summary) — numbered from 1 in list order."""
    context = get_settings().doc_context == "on"

    def about(s: dict) -> str:
        return f"About this file: {first_sentence(s['summary'])}\n" if context and s.get("summary") else ""

    return "\n\n".join(
        f"[{i}] ({s['title']}, {where(s)})\n{about(s)}{s['text']}" for i, s in enumerate(sources, start=1)
    )
```

- [ ] **Step 5: Summary embeddings in the worker** (`backend/app/enrich/worker.py`)

Replace `_after_write` with the following, keeping the Task 6 body after the new first block:

```python
    def _after_write(self, doc: dict, ok: bool) -> None:
        if ok:
            self._embed_pending_summaries()
        with get_pool().connection() as conn, conn.transaction():
            vocab.relink(conn, doc["course"])
            pending = conn.execute(
                f"SELECT 1 FROM documents WHERE {PENDING} AND course IS NOT DISTINCT FROM %s::text LIMIT 1",
                (doc["course"],)).fetchone()
        if pending is None:
            vocab.run(doc["course"], embed=self.embed)

    def _embed_pending_summaries(self, limit: int = 16) -> int:
        """bge-m3 vectors (CPU) for current summaries that lack one. Returns how many were embedded."""
        with get_pool().connection() as conn:
            rows = conn.execute(
                """SELECT id, sha256, summary FROM documents
                   WHERE enrich_status = 'ok' AND enriched_sha = sha256 AND summary IS NOT NULL
                     AND summary_embedding IS NULL ORDER BY id LIMIT %s""", (limit,)).fetchall()
            if not rows:
                return 0
            vectors = (self.embed or ollama.embed)([r["summary"] for r in rows])
            for r, v in zip(rows, vectors, strict=True):
                conn.execute("UPDATE documents SET summary_embedding = %s WHERE id = %s AND sha256 = %s",
                             (v, r["id"], r["sha256"]))
        return len(rows)
```

Replace the top of `step()`, from `s = get_settings()` through the `chunks = …fetchall()` line, with:

```python
        s = get_settings()
        if not s.enrich_enabled or s.enrich_paused:
            return False
        with get_pool().connection() as conn:
            doc = conn.execute(
                f"SELECT id, sha256, title, course FROM documents WHERE {PENDING} ORDER BY ingested_at, id LIMIT 1"
            ).fetchone()
            chunks = conn.execute(
                "SELECT text, n_tokens FROM chunks WHERE document_id = %s ORDER BY ord", (doc["id"],)
            ).fetchall() if doc else []
        if doc is None:  # nothing to summarise: backfill vectors for summaries made before stage 3
            return self._embed_pending_summaries() > 0
```

- [ ] **Step 6: Settings and eval params**

In `backend/app/admin/settings.py`, add to `EDITABLE`, after `min_score`:

```python
    Field("doc_boost", "Retrieval", "Summary boost", "float",
          "Ranks passages higher when their file's summary matches the question; 0 is off", 0, 1),
```

and after `temperature`:

```python
    Field("doc_context", "Answers", "File context", "choice",
          "on: each passage the model reads starts with its file's summary", options=("off", "on")),
```

In `backend/app/eval/run.py`, add `"doc_boost": s.doc_boost, "doc_context": s.doc_context` to `params`.

- [ ] **Step 7: Run all the tests**

Run: `uv run pytest`
Expected: all PASS. If `test_settings.py` compares the full list of editable keys, add the two new ones. If `test_llm.py` compares `format_context` output exactly, it still passes, because `doc_context` defaults to off.

- [ ] **Step 8: Commit**

```bash
git add backend/app/enrich/worker.py backend/app/rag/retrieve.py backend/app/llm/prompts.py backend/app/admin/settings.py backend/app/eval/run.py backend/tests/
git commit -m "Retrieval experiment: summary boost in dense ranking and file context in prompts, both off by default"
```

---

### Task 10: Evaluation sweep and the decision

**Files:**
- Modify: `README.md`, and `config.yaml` only if a setting wins

- [ ] **Step 1: Check the preconditions**

Every `ok` document must have a summary embedding:

```bash
docker compose exec postgres psql -U secondbrain -c "SELECT count(*) FILTER (WHERE summary_embedding IS NULL) AS missing, count(*) FROM documents WHERE status = 'ok'"
```

Expected: `missing` = 0. If not, leave the backend running until the worker's backfill finishes.

Pause enrichment in `/admin` (or stop the backend) for the whole sweep. The CLI runs in its own process, so the worker can't see it, and would otherwise compete for the GPU during full runs.

- [ ] **Step 2: Sweep `doc_boost`** (from `backend/`, about 3 minutes each)

```bash
DOC_BOOST=0 uv run python -m app.eval.run
```

```bash
DOC_BOOST=0.1 uv run python -m app.eval.run
```

```bash
DOC_BOOST=0.2 uv run python -m app.eval.run
```

```bash
DOC_BOOST=0.3 uv run python -m app.eval.run
```

(In PowerShell: `$env:DOC_BOOST='0.1'; uv run python -m app.eval.run`, then `Remove-Item Env:DOC_BOOST` at the end.)

For each run, record dense recall@1, @5 and @20 and MRR overall, and recall@5 for French and for English, from `/admin` Evaluation.

- [ ] **Step 3: `doc_context`, in full runs** (about 20 minutes each)

Use the best `doc_boost` from Step 2, or 0 if none won:

```bash
DOC_CONTEXT=off uv run python -m app.eval.run --full
```

```bash
DOC_CONTEXT=on uv run python -m app.eval.run --full
```

Record citations valid, cited the right page, and the median answer time.

- [ ] **Step 4: Decide**

- A `doc_boost` value becomes the default only if both hold:
  - it raises overall recall@5 or recall@1 over the 0 run;
  - it doesn't lower French or English recall@5 by more than 2 points.
- `doc_context` becomes `on` only if both hold:
  - it raises "cited the right page" without lowering "citations valid";
  - the median answer time rises by less than 10%.
- If a setting wins, put it in `config.yaml` with a comment citing the numbers. Otherwise leave the defaults.

- [ ] **Step 5: README**

Add a paragraph to the "Evaluation" section, after the baseline table:

```markdown
Summary experiments (<date>, <n> generated questions):

| doc_boost | recall@1 | recall@5 | recall@20 | MRR | FR recall@5 | EN recall@5 |
|---|---|---|---|---|---|---|
| 0 | … | … | … | … | … | … |
| 0.1 | … | … | … | … | … | … |
| 0.2 | … | … | … | … | … | … |
| 0.3 | … | … | … | … | … | … |

File context in prompts, full runs: citations valid … vs …, cited the right page … vs …, median answer … vs … s.
Decision: <what is on by default now, and why>.
```

Also update the Roadmap:
- v2: "tags/summaries (done)";
- the "Configuration" section: one line for each of `doc_boost` and `doc_context`.

- [ ] **Step 6: Update the auto-memory eval baseline**

If a setting became the default, update `eval-baseline.md` in the user's Claude memory with the new numbers.

- [ ] **Step 7: Commit**

```bash
git add README.md config.yaml
git commit -m "Evaluation: summary boost and file context measured; <decision>"
```
