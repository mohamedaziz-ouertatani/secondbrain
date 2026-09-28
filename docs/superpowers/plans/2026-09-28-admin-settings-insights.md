# Admin Panel Part 2 (Settings + Insights) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit retrieval and answer settings from `/admin` without a restart, saved to a git-ignored `config.local.yaml`, and see query-log insights: numbers, trend, problem lists, and a dense vs hybrid comparison.

**Architecture:** `config.py` gains a local YAML layer between `.env` and `config.yaml`. Its file paths are module globals read at call time, so tests can redirect them. `app/admin/settings.py` describes the editable keys, resolves each value's source, validates changes all-or-nothing, writes the file atomically and clears the settings cache. `app/admin/insights.py` runs SQL over `query_log` and the comparison. `retrieve()` splits so a precomputed vector can be reused. The frontend adds a Settings section and an Insights section to `/admin`.

**Tech Stack:** FastAPI, pydantic-settings 2.15 (yaml), PyYAML, python-dotenv, psycopg 3, pytest; Next.js 16 client components, inline SVG, plain CSS.

**Spec:** `docs/superpowers/specs/2026-09-28-admin-settings-insights-design.md`

## Global Constraints

- Precedence: env > `.env` > `config.local.yaml` > `config.yaml` > defaults.
- `config.local.yaml` is git-ignored, and only keys changed in the panel go in it. `config.yaml` is never written.
- Ranges: `top_k` 1–10; `candidate_k` 5–100 and ≥ the effective `top_k`; `rrf_k` 1–200; `min_score` 0–1; `temperature` 0–1.5; `num_ctx` 1024–32768; `llm_keep_alive` matches `^(-1|0|\d+[smh])$`; `llm_model` must be pulled and not the embed model; `retrieval_mode` is `dense` or `hybrid`.
- `PUT /admin/settings` is all-or-nothing: 422 with `{"detail": {key: reason}}` and nothing written.
- Insights `tz` must be in `pg_timezone_names`, or 400. `days=0` means all time.
- `POST /admin/compare` shares the 409 job guard (`app/api/jobs.exclusive`). `limit` is 1–50.
- CORS must allow `PUT`.
- Postgres is on 5433. Backend commands run from `backend/` with `uv run`; frontend commands from `frontend/`. Frontend checks: `npx tsc --noEmit`, `npm run lint`, then the browser pane.
- UI follows `DESIGN.md` (card catalogue): tints only mean "filed in this unit", no coloured side stripes. The chart follows the `dataviz` skill.

---

### Task 1: Settings layer and API

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.gitignore` (add `config.local.yaml`)
- Modify: `backend/app/llm/ollama.py` (add `pulled()`)
- Create: `backend/app/admin/settings.py`
- Modify: `backend/app/api/admin.py` (GET/PUT `/admin/settings`)
- Modify: `backend/app/main.py` (CORS `PUT`)
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `config.BASE_CONFIG`, `config.LOCAL_CONFIG`, `config.ENV_FILE` (paths, patchable)
  - `Settings.retrieval_mode: Literal["dense", "hybrid"]`
  - `ollama.pulled() -> list[str] | None`
  - `admin.settings.view() -> dict` (shape in the spec)
  - `admin.settings.update(changes: dict) -> dict`, which raises `admin.settings.Invalid` with `.errors: dict[str, str]`
  - `admin.settings.source(key) -> tuple[str, str | None]`
  - HTTP `GET /admin/settings`, `PUT /admin/settings`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_settings.py`:

```python
import pytest

KEYS = ("top_k", "candidate_k", "rrf_k", "min_score", "retrieval_mode", "llm_model",
        "temperature", "num_ctx", "llm_keep_alive", "embed_model")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point the settings layers at temp files, clear any real env overrides, fake Ollama's model list."""
    from app import config
    from app.llm import ollama

    base = tmp_path / "config.yaml"
    base.write_text("top_k: 5\ncandidate_k: 20\nllm_model: qwen3:4b-instruct\n", encoding="utf-8")
    monkeypatch.setattr(config, "BASE_CONFIG", base)
    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    for k in KEYS:
        monkeypatch.delenv(k.upper(), raising=False)
    monkeypatch.setattr(ollama, "pulled", lambda: ["bge-m3:latest", "qwen2.5:3b", "qwen3:4b-instruct"])
    config.get_settings.cache_clear()
    yield tmp_path
    config.get_settings.cache_clear()


def local(tmp):
    import yaml

    p = tmp / "config.local.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def test_precedence_and_sources(cfg, monkeypatch):
    from app.admin.settings import source
    from app.config import get_settings

    assert get_settings().top_k == 5 and source("top_k") == ("config", None)
    assert source("rrf_k") == ("default", None)

    (cfg / "config.local.yaml").write_text("top_k: 3\n", encoding="utf-8")
    get_settings.cache_clear()
    assert get_settings().top_k == 3 and source("top_k") == ("local", None)

    (cfg / ".env").write_text("RRF_K=40\n", encoding="utf-8")
    monkeypatch.setenv("TOP_K", "7")
    get_settings.cache_clear()
    assert get_settings().top_k == 7 and source("top_k") == ("env", "TOP_K")
    assert get_settings().rrf_k == 40 and source("rrf_k") == ("env", "RRF_K")


def test_update_writes_validates_and_resets(cfg):
    from app.admin.settings import Invalid, update
    from app.config import get_settings

    update({"top_k": 4, "retrieval_mode": "hybrid", "llm_model": "qwen2.5:3b"})
    assert local(cfg) == {"llm_model": "qwen2.5:3b", "retrieval_mode": "hybrid", "top_k": 4}
    assert get_settings().top_k == 4  # cache cleared, no restart

    bad = [
        ({"top_k": 11}, "top_k"),
        ({"top_k": True}, "top_k"),
        ({"candidate_k": 3}, "candidate_k"),  # below the effective top_k (4)
        ({"llm_keep_alive": "forever"}, "llm_keep_alive"),
        ({"llm_model": "llama3:70b"}, "llm_model"),  # not pulled
        ({"llm_model": "bge-m3:latest"}, "llm_model"),  # the embed model
        ({"retrieval_mode": "sparse"}, "retrieval_mode"),
        ({"embed_model": "x"}, "embed_model"),  # read-only
        ({"nope": 1}, "nope"),
        ({"top_k": 3, "rrf_k": 0}, "rrf_k"),  # all or nothing: top_k must not be written either
    ]
    for change, key in bad:
        with pytest.raises(Invalid) as e:
            update(change)
        assert key in e.value.errors, change
        assert local(cfg)["top_k"] == 4, change

    update({"top_k": None})  # reset
    assert "top_k" not in local(cfg)
    assert get_settings().top_k == 5


def test_env_locked_key_is_refused(cfg, monkeypatch):
    from app.admin.settings import Invalid, update, view

    monkeypatch.setenv("TOP_K", "6")
    row = next(r for g in view()["groups"] for r in g["rows"] if r["key"] == "top_k")
    assert row["source"] == "env" and row["locked_by"] == "TOP_K" and row["value"] == 6
    with pytest.raises(Invalid) as e:
        update({"top_k": 2})
    assert "TOP_K" in e.value.errors["top_k"]


def test_routes(cfg):
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    v = client.get("/admin/settings").json()
    assert [g["name"] for g in v["groups"]] == ["Retrieval", "Answers"]
    model = next(r for r in v["groups"][1]["rows"] if r["key"] == "llm_model")
    assert model["options"] == ["qwen2.5:3b", "qwen3:4b-instruct"]
    assert {r["key"] for r in v["readonly"]} >= {"embed_model", "database_url", "watch_dir"}
    assert "secondbrain:secondbrain@" not in next(r["value"] for r in v["readonly"] if r["key"] == "database_url")

    r = client.put("/admin/settings", json={"top_k": 99})
    assert r.status_code == 422 and "top_k" in r.json()["detail"]
    r = client.put("/admin/settings", json={"top_k": 3})
    assert r.status_code == 200
    assert next(x for x in r.json()["groups"][0]["rows"] if x["key"] == "top_k")["value"] == 3

    pre = client.options("/admin/settings", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT"})
    assert pre.status_code == 200
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.admin.settings'`.

- [ ] **Step 3: `app/config.py`**

Replace the imports and class header so that the sources read module globals at call time:

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"  # written by the admin panel; git-ignored
ENV_FILE = ROOT / ".env"


class Settings(BaseSettings):
    """Precedence: env vars > .env > config.local.yaml (admin panel) > config.yaml > defaults below."""

    model_config = SettingsConfigDict(extra="ignore")
```

Change `retrieval_mode: str = "dense"  # or "hybrid"` to `retrieval_mode: Literal["dense", "hybrid"] = "dense"`, and the sources method to:

```python
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # module globals, read per call, so tests can point them at temp files
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=ENV_FILE),
            YamlConfigSettingsSource(settings_cls, yaml_file=LOCAL_CONFIG),
            YamlConfigSettingsSource(settings_cls, yaml_file=BASE_CONFIG),
        )
```

Append `config.local.yaml` to `.gitignore` under `.env`.

- [ ] **Step 4: `ollama.pulled()`**

Add to `app/llm/ollama.py` after `loaded()`:

```python
def pulled() -> list[str] | None:
    """Names of the models Ollama has pulled, sorted; None if Ollama is unreachable."""
    try:
        return sorted(m["name"] for m in _client().get("/api/tags", timeout=5).json().get("models", []))
    except httpx.HTTPError:
        return None
```

- [ ] **Step 5: `app/admin/settings.py`**

```python
"""Settings the admin panel can change: where each value comes from, validation, saving to config.local.yaml."""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values

from .. import config
from ..llm import ollama


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    control: str  # int | float | choice | text
    help: str
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] | None = None
    pattern: str | None = None


EDITABLE = (
    Field("retrieval_mode", "Retrieval", "Retrieval mode", "choice",
          "dense: vectors only. hybrid: vectors plus keyword search, fused.", options=("dense", "hybrid")),
    Field("top_k", "Retrieval", "Passages per answer", "int", "How many passages the model reads", 1, 10),
    Field("candidate_k", "Retrieval", "Candidates per list", "int", "Hybrid only: passages taken from each list before fusion", 5, 100),
    Field("rrf_k", "Retrieval", "Fusion constant", "int", "Hybrid only: higher flattens the rank bonus", 1, 200),
    Field("min_score", "Retrieval", "Refusal threshold", "float", "Refuse unless a passage is at least this close", 0, 1),
    Field("llm_model", "Answers", "Model", "choice", "The model that writes answers; the next question loads it"),
    Field("temperature", "Answers", "Temperature", "float", "Lower is more literal", 0, 1.5),
    Field("num_ctx", "Answers", "Context window", "int", "Tokens the model sees; larger uses more VRAM", 1024, 32768),
    Field("llm_keep_alive", "Answers", "Keep loaded for", "text",
          "After a question: 30m, 2h, 0 (unload at once) or -1 (never)", pattern=r"^(-1|0|\d+[smh])$"),
)
FIELDS = {f.key: f for f in EDITABLE}
READONLY = {
    "embed_model": "Changing it means re-indexing everything",
    "embed_dim": "Changing it means re-indexing everything",
    "chunk_tokens": "Changing it means re-indexing everything",
    "chunk_overlap": "Changing it means re-indexing everything",
    "database_url": "Needs a backend restart",
    "ollama_url": "Needs a backend restart",
    "watch_dir": "Needs a backend restart",
}


class Invalid(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__(errors)
        self.errors = errors


def _yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def source(key: str) -> tuple[str, str | None]:
    """Where the effective value comes from: env (with the variable's name), local, config or default."""
    name = key.upper()
    if name in os.environ or name in dotenv_values(config.ENV_FILE):
        return "env", name
    if key in _yaml(config.LOCAL_CONFIG):
        return "local", None
    if key in _yaml(config.BASE_CONFIG):
        return "config", None
    return "default", None


def _model_options() -> list[str] | None:
    names = ollama.pulled()
    if names is None:
        return None
    embed = config.get_settings().embed_model
    return [n for n in names if n not in (embed, f"{embed}:latest")]


def view() -> dict:
    s = config.get_settings()
    models = _model_options()
    groups: dict[str, list[dict]] = {}
    for f in EDITABLE:
        src, locked = source(f.key)
        options = list(f.options) if f.options else (models if f.key == "llm_model" else None)
        groups.setdefault(f.group, []).append({
            "key": f.key, "label": f.label, "value": getattr(s, f.key), "source": src, "locked_by": locked,
            "editable": locked is None, "control": f.control, "help": f.help,
            "min": f.min, "max": f.max, "options": options,
        })
    readonly = []
    for key, reason in READONLY.items():
        value = str(getattr(s, key))
        if key == "database_url":
            value = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:•••@", value)
        readonly.append({"key": key, "value": value, "reason": reason})
    return {"groups": [{"name": g, "rows": rows} for g, rows in groups.items()], "readonly": readonly}


def _check(f: Field, v) -> str | None:
    if f.control == "int":
        if not isinstance(v, int) or isinstance(v, bool):
            return "must be a whole number"
    elif f.control == "float":
        if not isinstance(v, int | float) or isinstance(v, bool):
            return "must be a number"
    elif f.control == "text":
        if not isinstance(v, str) or (f.pattern and not re.fullmatch(f.pattern, v)):
            return "use a duration like 30m, 2h, 0 or -1"
    if f.min is not None and not (f.min <= v <= f.max):
        return f"must be between {f.min:g} and {f.max:g}"
    if f.key == "llm_model":
        models = _model_options()
        if models is None:
            return "Ollama isn't reachable, so the model can't be checked"
        if v not in models:
            return "not a pulled chat model; pull it with ollama pull first"
    elif f.options and v not in f.options:
        return f"must be one of {', '.join(f.options)}"
    return None


def update(changes: dict) -> dict:
    """Validate every change, then write them all or none. None as a value resets the key."""
    errors: dict[str, str] = {}
    for key, v in changes.items():
        f = FIELDS.get(key)
        if f is None:
            errors[key] = READONLY.get(key, "not a setting the panel can change")
            continue
        _, locked = source(key)
        if locked:
            errors[key] = f"set by the environment variable {locked}; change it there"
        elif v is not None and (err := _check(f, v)):
            errors[key] = err

    new_local = {**_yaml(config.LOCAL_CONFIG)}
    for key, v in changes.items():
        if key not in errors and key in FIELDS:
            if v is None:
                new_local.pop(key, None)
            else:
                new_local[key] = v

    def effective(key: str):
        if source(key)[1]:
            return getattr(config.get_settings(), key)
        if key in new_local:
            return new_local[key]
        base = _yaml(config.BASE_CONFIG)
        return base[key] if key in base else config.Settings.model_fields[key].default

    if not errors and effective("candidate_k") < effective("top_k"):
        errors["candidate_k" if "candidate_k" in changes else "top_k"] = "candidates per list can't be fewer than passages per answer"
    if errors:
        raise Invalid(errors)

    path = config.LOCAL_CONFIG
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write("# Written by the admin panel. Overrides config.yaml; environment variables override this.\n")
        yaml.safe_dump(dict(sorted(new_local.items())), tmp, allow_unicode=True)
    os.replace(tmp.name, path)
    config.get_settings.cache_clear()
    return view()
```

- [ ] **Step 6: Routes and CORS**

In `app/api/admin.py`, add `from typing import Any`, `from ..admin.settings import Invalid, update, view` and:

```python
@router.get("/settings")
def get_settings_view() -> dict:
    return view()


@router.put("/settings")
def put_settings(changes: dict[str, Any]) -> dict:
    try:
        return update(changes)
    except Invalid as e:
        raise HTTPException(422, e.errors) from e
```

In `app/main.py`: `allow_methods=["GET", "POST", "PUT", "DELETE"]`.

- [ ] **Step 7: Run all tests and lint**

Run: `uv run pytest -q && uv run ruff check --output-format concise app/config.py app/admin app/api/admin.py app/llm/ollama.py tests/test_settings.py`
Expected: 59 passed (55 + 4); no findings in these files.

- [ ] **Step 8: Commit**

```bash
git add .gitignore backend/app/config.py backend/app/llm/ollama.py backend/app/admin/settings.py backend/app/api/admin.py backend/app/main.py backend/tests/test_settings.py
git commit -m "Admin settings: edit retrieval and answer settings live, saved to config.local.yaml"
```

---

### Task 2: Insights and comparison API

**Files:**
- Modify: `backend/app/rag/retrieve.py` (split out `retrieve_with_vector`)
- Create: `backend/app/admin/insights.py`
- Modify: `backend/app/rag/compare.py` (CLI on top of `insights.compare`)
- Modify: `backend/app/api/admin.py` (three routes)
- Test: `backend/tests/test_insights.py`

**Interfaces:**
- Consumes: `NOT_FOUND` (`app/llm/prompts.py`), `jobs.exclusive`, `fakes.fake_embed`/`words`.
- Produces:
  - `retrieve_with_vector(qvec, question: str, course: str | None = None, mode: str | None = None) -> tuple[list[dict], list[dict]]`
  - `insights.summary(days: int, tz: str) -> dict` (raises `ValueError` on an unknown tz)
  - `insights.problems(kind: str, days: int, limit: int) -> list[dict]`
  - `insights.compare(limit: int = 20) -> dict`
  - HTTP `GET /admin/insights`, `GET /admin/insights/problems`, `POST /admin/compare`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_insights.py`:

```python
from fakes import fake_embed, words
from psycopg.types.json import Jsonb


def log(db, question, course=None, answer="Answer [1].", valid=True, ms=5000, ts="now()"):
    with db.get_pool().connection() as conn:
        return conn.execute(
            f"""INSERT INTO query_log (ts, question, params, answer, citation_valid, latency_ms)
                VALUES ({ts}, %s, %s, %s, %s, %s) RETURNING id""",
            (question, Jsonb({"course": course}), answer, valid, ms),
        ).fetchone()["id"]


def test_summary_counts_medians_and_filters(env):
    from app.admin.insights import summary
    from app.llm.prompts import NOT_FOUND

    _, db = env
    log(db, "a", "Prob", ms=4000)
    log(db, "b", "Prob", answer=NOT_FOUND, valid=None, ms=1000)
    log(db, "c", None, valid=False, ms=9000)
    log(db, "d", None, answer=None, valid=None, ms=None)
    log(db, "old", "Prob", ms=60000, ts="now() - interval '40 days'")

    s = summary(7, "UTC")
    assert (s["questions"], s["refused"], s["invalid"], s["failed"]) == (4, 1, 1, 1)
    assert s["median_ms"] == 4000 and s["max_ms"] == 9000
    assert s["per_module"][0] == {"course": "Prob", "questions": 2, "refused": 1}
    assert summary(0, "UTC")["questions"] == 5 and summary(0, "UTC")["max_ms"] == 60000


def test_per_day_follows_the_time_zone(env):
    from app.admin.insights import summary

    _, db = env
    log(db, "late", ts="'2026-09-27 23:30:00+00'")  # 00:30 on the 28th in Tunis
    assert [d["day"] for d in summary(0, "UTC")["per_day"]] == ["2026-09-27"]
    assert [d["day"] for d in summary(0, "Africa/Tunis")["per_day"]] == ["2026-09-28"]


def test_problems_order(env):
    from app.admin.insights import problems
    from app.llm.prompts import NOT_FOUND

    _, db = env
    r1 = log(db, "r1", answer=NOT_FOUND, valid=None)
    r2 = log(db, "r2", answer=NOT_FOUND, valid=None)
    fast = log(db, "fast", ms=1000)
    slow = log(db, "slow", ms=90000)
    assert [p["id"] for p in problems("refused", 7, 50)] == [r2, r1]
    assert [p["id"] for p in problems("slow", 7, 2)] == [slow, fast]
    assert problems("invalid", 7, 50) == []


def test_routes_and_compare(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.admin import insights
    from app.ingest import pipeline
    from app.main import create_app

    inbox, db = env
    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    monkeypatch.setattr(insights.ollama, "embed", fake_embed)
    (inbox / "Prob").mkdir()
    (inbox / "Prob" / "g.md").write_text("Un vecteur gaussien a une fonction caractéristique. " * 20, encoding="utf-8")
    pipeline.rescan()
    log(db, "vecteur gaussien", "Prob")
    log(db, "vecteur gaussien", "Prob")  # duplicate: compared once
    log(db, "brownian motion", None)

    client = TestClient(create_app())
    assert client.get("/admin/insights", params={"days": 7, "tz": "Mars/Olympus"}).status_code == 400
    assert client.get("/admin/insights", params={"days": 7, "tz": "Africa/Tunis"}).json()["questions"] == 3
    assert client.get("/admin/insights/problems", params={"kind": "bogus"}).status_code == 422

    out = client.post("/admin/compare", json={"limit": 20}).json()
    assert out["summary"]["questions"] == 2
    row = out["rows"][0]
    assert set(row) == {"question", "course", "dense", "hybrid", "verdict_dense", "verdict_hybrid", "changed"}
    assert row["verdict_dense"] in ("answer", "refuse") and all("chunk_id" in h for h in row["dense"])
    assert client.post("/admin/compare", json={"limit": 0}).status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_insights.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.admin.insights'`.

- [ ] **Step 3: Split `retrieve` (`app/rag/retrieve.py`)**

Replace `retrieve` with:

```python
def retrieve(question: str, course: str | None = None, mode: str | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (all candidates, the ones passed to the LLM)."""
    return retrieve_with_vector(ollama.embed([question])[0], question, course, mode)


def retrieve_with_vector(
    qvec, question: str, course: str | None = None, mode: str | None = None
) -> tuple[list[dict], list[dict]]:
    """retrieve() with the question already embedded, so one vector can serve both modes."""
    s = get_settings()
    mode = mode or s.retrieval_mode
    with get_pool().connection() as conn:
        if mode == "dense":
            hits = _dense(conn, qvec, s.top_k, course)
            return hits, [h for h in hits if h["score"] >= s.min_score]
        dense_hits = _dense(conn, qvec, s.candidate_k, course)
        lexical_hits = _lexical(conn, qvec, keywords(question), s.candidate_k, course)
    hits = fuse(dense_hits, lexical_hits, s.rrf_k)
    return hits, hits[: s.top_k] if answerable(hits, s.min_score) else []
```

- [ ] **Step 4: `app/admin/insights.py`**

```python
"""Query-log insights for the admin panel: health numbers, daily trend, problem lists, dense vs hybrid."""

from ..db import get_pool
from ..llm import ollama
from ..llm.prompts import NOT_FOUND
from ..rag.retrieve import retrieve_with_vector

PROBLEMS = {
    "refused": ("answer = %(nf)s", "id DESC"),
    "invalid": ("citation_valid IS false", "id DESC"),
    "slow": ("latency_ms IS NOT NULL", "latency_ms DESC, id DESC"),
}


def _since(days: int) -> str:
    return "ts >= now() - make_interval(days => %(days)s)" if days else "true"


def _ms(v) -> int | None:
    return None if v is None else int(v)


def summary(days: int, tz: str) -> dict:
    p = {"days": days, "tz": tz, "nf": NOT_FOUND}
    where = _since(days)
    with get_pool().connection() as conn:
        if not conn.execute("SELECT 1 FROM pg_timezone_names WHERE name = %s", (tz,)).fetchone():
            raise ValueError(f"unknown time zone: {tz}")
        head = conn.execute(
            f"""SELECT count(*) AS questions,
                       count(*) FILTER (WHERE answer = %(nf)s) AS refused,
                       count(*) FILTER (WHERE citation_valid IS false) AS invalid,
                       count(*) FILTER (WHERE answer IS NULL) AS failed,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_ms,
                       max(latency_ms) AS max_ms
                FROM query_log WHERE {where}""", p).fetchone()
        per_module = conn.execute(
            f"""SELECT params->>'course' AS course, count(*) AS questions,
                       count(*) FILTER (WHERE answer = %(nf)s) AS refused
                FROM query_log WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST""", p).fetchall()
        per_day = conn.execute(
            f"""SELECT (ts AT TIME ZONE %(tz)s)::date AS day, count(*) AS questions,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_ms
                FROM query_log WHERE {where} GROUP BY 1 ORDER BY 1""", p).fetchall()
    return {
        **head, "median_ms": _ms(head["median_ms"]), "max_ms": _ms(head["max_ms"]),
        "per_module": per_module,
        "per_day": [{"day": d["day"].isoformat(), "questions": d["questions"], "median_ms": _ms(d["median_ms"])}
                    for d in per_day],
    }


def problems(kind: str, days: int, limit: int) -> list[dict]:
    cond, order = PROBLEMS[kind]
    with get_pool().connection() as conn:
        return conn.execute(
            f"""SELECT id, ts, question, params->>'course' AS course, latency_ms FROM query_log
                WHERE {cond} AND {_since(days)} ORDER BY {order} LIMIT %(limit)s""",
            {"nf": NOT_FOUND, "days": days, "limit": limit},
        ).fetchall()


def _brief(h: dict) -> dict:
    return {"chunk_id": h["chunk_id"], "title": h["title"], "page": h["page"], "label": h["label"],
            "score": round(float(h["score"]), 3)}


def compare(limit: int = 20) -> dict:
    """Replay the most recent distinct questions through dense and hybrid retrieval, one embedding each."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT question, course FROM (
                   SELECT DISTINCT ON (question, params->>'course') question, params->>'course' AS course, id
                   FROM query_log ORDER BY question, params->>'course', id DESC) q
               ORDER BY id DESC LIMIT %s""",
            (limit,),
        ).fetchall()
    vectors = ollama.embed([r["question"] for r in rows]) if rows else []
    out, changed, flipped = [], 0, 0
    for r, qvec in zip(rows, vectors, strict=True):
        _, dense = retrieve_with_vector(qvec, r["question"], r["course"], "dense")
        _, hybrid = retrieve_with_vector(qvec, r["question"], r["course"], "hybrid")
        diff = {h["chunk_id"] for h in dense} != {h["chunk_id"] for h in hybrid}
        flip = bool(dense) != bool(hybrid)
        changed += diff
        flipped += flip
        out.append({
            "question": r["question"], "course": r["course"],
            "dense": [_brief(h) for h in dense], "hybrid": [_brief(h) for h in hybrid],
            "verdict_dense": "answer" if dense else "refuse",
            "verdict_hybrid": "answer" if hybrid else "refuse",
            "changed": diff,
        })
    return {"summary": {"questions": len(out), "changed": changed, "flipped": flipped}, "rows": out}
```

- [ ] **Step 5: Routes (`app/api/admin.py`)**

Add `from typing import Literal`, `from pydantic import Field` (next to `BaseModel`), `from ..admin.insights import compare, problems, summary` and:

```python
class CompareBody(BaseModel):
    limit: int = Field(20, ge=1, le=50)


@router.get("/insights")
def insights(days: int = 7, tz: str = "UTC") -> dict:
    if days < 0:
        raise HTTPException(400, "days must be 0 (all time) or more")
    try:
        return summary(days, tz)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/insights/problems")
def insight_problems(kind: Literal["refused", "invalid", "slow"], days: int = 7, limit: int = 50) -> list[dict]:
    return problems(kind, max(0, days), max(1, min(limit, 200)))


@router.post("/compare")
def admin_compare(body: CompareBody) -> dict:
    with exclusive("compare"):
        return compare(body.limit)
```

- [ ] **Step 6: CLI on top (`app/rag/compare.py`)**

Replace the body of `main()` with a printer over `insights.compare(args.limit)`. Keep the `--limit` flag and the `get_pool().close()` at the end:

```python
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=20, help="most recent distinct questions to replay (max 50)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    from ..admin.insights import compare

    out = compare(max(1, min(args.limit, 50)))
    for r in out["rows"]:
        dense_ids = {h["chunk_id"] for h in r["dense"]}
        hybrid_ids = {h["chunk_id"] for h in r["hybrid"]}
        print(f"\n{r['question']}" + (f"  [{r['course']}]" if r["course"] else ""))
        print(f"  dense: {r['verdict_dense']}   hybrid: {r['verdict_hybrid']}")
        for h in r["hybrid"]:
            print(f"  {'+' if h['chunk_id'] not in dense_ids else ' '} {_label(h)[:70]:70}  cos {h['score']:.2f}")
        for h in r["dense"]:
            if h["chunk_id"] not in hybrid_ids:
                print(f"  - {_label(h)[:70]:70}  cos {h['score']:.2f}")
    s = out["summary"]
    print(f"\n{s['questions']} questions: {s['changed']} with different passages, "
          f"{s['flipped']} with a different answer/refuse decision")
    get_pool().close()
```

Drop the now-unused imports (`keywords`, `retrieve`). `_label` stays. It works on the brief dicts because they carry `title`, `label` and `page`.

- [ ] **Step 7: Run all tests and lint**

Run: `uv run pytest -q && uv run ruff check --output-format concise app/admin app/api/admin.py app/rag tests/test_insights.py`
Expected: 63 passed (59 + 4); no new findings.

- [ ] **Step 8: Commit**

```bash
git add backend/app/rag/retrieve.py backend/app/rag/compare.py backend/app/admin/insights.py backend/app/api/admin.py backend/tests/test_insights.py
git commit -m "Admin insights: query-log numbers, daily trend, problem lists, dense vs hybrid comparison"
```

---

### Task 3: Settings section on /admin

**Files:**
- Modify: `frontend/lib/api.ts` (`SettingRow`, `SettingsView`, `ApiError`, `sendJSON`; `postJSON` delegates to it)
- Create: `frontend/components/admin/SettingsCard.tsx`
- Modify: `frontend/app/admin/page.tsx`, `frontend/app/globals.css`

**Interfaces:**
- Consumes: `GET`/`PUT /admin/settings` (Task 1).
- Produces:
  - `class ApiError extends Error { status: number; detail: unknown }`
  - `sendJSON<T>(method: "POST" | "PUT", path: string, body: unknown): Promise<T>`
  - `<SettingsCard />`

- [ ] **Step 1: API helpers (`lib/api.ts`)**

Replace `postJSON` with:

```ts
/** An API error that keeps FastAPI's `detail` (a string, or a {field: reason} map for settings). */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail: unknown,
  ) {
    super(message);
  }
}

export async function sendJSON<T>(method: "POST" | "PUT", path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(`Can't reach the backend at ${API_URL}.`, 0, null);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    throw new ApiError(typeof detail === "string" ? detail : `${path} returned ${res.status}`, res.status, detail);
  }
  return data as T;
}

/** POST JSON; throws with the backend's `detail` so the UI can show why an action failed. */
export function postJSON<T>(path: string, body: unknown): Promise<T> {
  return sendJSON<T>("POST", path, body);
}

export type SettingRow = {
  key: string;
  label: string;
  value: string | number;
  source: "env" | "local" | "config" | "default";
  locked_by: string | null;
  editable: boolean;
  control: "int" | "float" | "choice" | "text";
  help: string;
  min: number | null;
  max: number | null;
  options: string[] | null;
};

export type SettingsView = {
  groups: { name: string; rows: SettingRow[] }[];
  readonly: { key: string; value: string; reason: string }[];
};
```

- [ ] **Step 2: `components/admin/SettingsCard.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getJSON, sendJSON, type SettingRow, type SettingsView } from "@/lib/api";

const SOURCE: Record<SettingRow["source"], string> = {
  default: "default",
  config: "config.yaml",
  local: "set here",
  env: "env",
};

type Draft = Record<string, string>;
const asText = (v: string | number) => String(v);

function parse(row: SettingRow, text: string): string | number {
  return row.control === "int" ? Number.parseInt(text, 10) : row.control === "float" ? Number(text) : text;
}

function Control({ row, value, onChange }: { row: SettingRow; value: string; onChange: (v: string) => void }) {
  const id = `set-${row.key}`;
  if (row.control === "choice")
    return (
      <select id={id} value={value} disabled={!row.editable} onChange={(e) => onChange(e.target.value)}>
        {(row.options ?? [asText(row.value)]).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  return (
    <input
      id={id}
      type={row.control === "text" ? "text" : "number"}
      inputMode={row.control === "text" ? undefined : "decimal"}
      min={row.min ?? undefined}
      max={row.max ?? undefined}
      step={row.control === "float" ? 0.01 : 1}
      value={value}
      disabled={!row.editable}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** Retrieval and answer settings, saved to config.local.yaml; applies from the next question. */
export function SettingsCard() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [note, setNote] = useState<{ group: string; text: string; bad?: boolean } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  const adopt = useCallback((v: SettingsView) => {
    setView(v);
    setDraft(Object.fromEntries(v.groups.flatMap((g) => g.rows.map((r) => [r.key, asText(r.value)]))));
  }, []);

  useEffect(() => {
    getJSON<SettingsView>("/admin/settings")
      .then(adopt)
      .catch(() => setLoadError(true));
  }, [adopt]);

  async function save(group: string, changes: Record<string, string | number | null>) {
    setSaving(group);
    setNote(null);
    setErrors({});
    try {
      adopt(await sendJSON<SettingsView>("PUT", "/admin/settings", changes));
      setNote({ group, text: "Saved. The next question uses these settings." });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.detail && typeof e.detail === "object")
        setErrors(e.detail as Record<string, string>);
      else setNote({ group, text: (e as Error).message, bad: true });
    } finally {
      setSaving(null);
    }
  }

  if (loadError) return <p className="notice bad">Couldn&apos;t load the settings.</p>;
  if (!view) return <p className="muted">Reading the settings…</p>;

  return (
    <>
      {view.groups.map((g) => {
        const dirty = g.rows.filter((r) => r.editable && draft[r.key] !== asText(r.value));
        return (
          <section key={g.name} className="admin-card" aria-labelledby={`g-${g.name}`}>
            <header className="admin-card-head">
              <h2 id={`g-${g.name}`}>{g.name} settings</h2>
              <span className="admin-actions">
                {note?.group === g.name && (
                  <span className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</span>
                )}
                <button
                  type="button"
                  className="quiet-btn"
                  disabled={dirty.length === 0 || saving !== null}
                  onClick={() => save(g.name, Object.fromEntries(dirty.map((r) => [r.key, parse(r, draft[r.key])])))}
                >
                  {saving === g.name ? "Saving…" : "Save changes"}
                </button>
              </span>
            </header>
            <dl className="kv settings">
              {g.rows.map((r) => (
                <div key={r.key} className="setting">
                  <dt>
                    <label htmlFor={`set-${r.key}`}>{r.label}</label>
                    <span className={`source ${r.source}`}>
                      {r.source === "env" ? `env: ${r.locked_by}` : SOURCE[r.source]}
                    </span>
                  </dt>
                  <dd>
                    <Control row={r} value={draft[r.key] ?? ""} onChange={(v) => setDraft({ ...draft, [r.key]: v })} />
                    {r.source === "local" && (
                      <button
                        type="button"
                        className="text-btn"
                        disabled={saving !== null}
                        onClick={() => save(g.name, { [r.key]: null })}
                      >
                        Reset
                      </button>
                    )}
                    <span className="help">{r.locked_by ? `Set by ${r.locked_by}; change it there.` : r.help}</span>
                    {errors[r.key] && <span className="field-error">{errors[r.key]}</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
      <details className="admin-card readonly">
        <summary>Fixed settings</summary>
        <dl className="kv">
          {view.readonly.map((r) => (
            <div key={r.key} className="setting">
              <dt>{r.key}</dt>
              <dd>
                <code>{r.value}</code>
                <span className="help">{r.reason}</span>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
```

Note: `.kv` is a `dl` grid. Rows are wrapped in `div.setting` (valid in a `dl`), so the `.settings` variant switches the grid to per-row layout. See the CSS step.

- [ ] **Step 3: Page and CSS**

In `app/admin/page.tsx`, import and render `<SettingsCard />` after `<LibraryAdmin />`.

Append to `app/globals.css`:

```css
/* ---- admin settings: one ruled row per setting ------------------------------------------ */
.kv.settings,
.readonly .kv {
  display: block;
}

.setting {
  display: grid;
  grid-template-columns: 12rem minmax(0, 1fr);
  gap: 0.2rem 1rem;
  padding: 0.55rem 0;
  border-bottom: 1px solid var(--rule-blue);
}

.setting:last-child {
  border-bottom: 0;
}

.setting dt,
.setting dd {
  border: 0;
  padding: 0;
}

.setting dt {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.9rem;
  color: var(--ink);
}

.setting dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.75rem;
}

.setting input,
.setting select {
  font: inherit;
  font-variant-numeric: tabular-nums;
  width: 12rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--rule-blue);
  border-radius: 4px;
  background: var(--card);
  color: var(--ink);
}

.setting input:disabled,
.setting select:disabled {
  background: var(--card-2);
  color: var(--muted);
}

.setting .help {
  flex-basis: 100%;
  font-size: 0.82rem;
  color: var(--muted);
}

.source {
  font-family: var(--type);
  font-size: 0.75rem;
  color: var(--muted);
}

.source.local {
  color: var(--primary);
}

.source.env {
  color: var(--bad);
}

.field-error {
  flex-basis: 100%;
  font-size: 0.84rem;
  color: var(--bad);
}

.text-btn {
  border: 0;
  background: none;
  padding: 0;
  color: var(--primary);
  font: inherit;
  font-size: 0.84rem;
  text-decoration: underline;
  text-underline-offset: 0.15em;
  cursor: pointer;
}

.readonly summary {
  cursor: pointer;
  font-weight: 600;
}

.readonly code {
  font-family: var(--type);
  font-size: 0.84rem;
}

@media (max-width: 860px) {
  .setting {
    grid-template-columns: minmax(0, 1fr);
  }
  .setting input,
  .setting select {
    width: 100%;
  }
}
```

- [ ] **Step 4: Typecheck, lint, commit**

Run: `npx tsc --noEmit && npm run lint`. Expected: clean.

```bash
git add frontend/lib/api.ts frontend/components/admin/SettingsCard.tsx frontend/app/admin/page.tsx frontend/app/globals.css
git commit -m "Admin page: settings section with sources, validation errors and reset"
```

---

### Task 4: Insights section on /admin

**Files:**
- Modify: `frontend/lib/api.ts` (`InsightsSummary`, `ProblemRow`, `CompareResult`)
- Create: `frontend/components/admin/TrendChart.tsx`, `frontend/components/admin/InsightsCard.tsx`
- Modify: `frontend/app/admin/page.tsx`, `frontend/app/globals.css`

**Interfaces:**
- Consumes: the Task 2 routes, `getJSON`, `postJSON`, `moduleCode`/`tintVar`, `openHref` (`lib/history.ts`).
- Produces: `<InsightsCard />`, `<TrendChart days={...} data={per_day} />`.

- [ ] **Step 1: Load the `dataviz` skill** before writing the chart. Follow its mark, axis and colour rules. The palette comes from `DESIGN.md` tokens (`--primary` for the latency line, `--tint-modeling` for the bars) and must hold in both themes.

- [ ] **Step 2: Types (`lib/api.ts`)**

```ts
export type InsightsSummary = {
  questions: number;
  refused: number;
  invalid: number;
  failed: number;
  median_ms: number | null;
  max_ms: number | null;
  per_module: { course: string | null; questions: number; refused: number }[];
  per_day: { day: string; questions: number; median_ms: number | null }[];
};

export type ProblemRow = { id: number; ts: string; question: string; course: string | null; latency_ms: number | null };

export type ComparedHit = { chunk_id: number; title: string; page: number; label: string | null; score: number };
export type CompareResult = {
  summary: { questions: number; changed: number; flipped: number };
  rows: {
    question: string;
    course: string | null;
    dense: ComparedHit[];
    hybrid: ComparedHit[];
    verdict_dense: "answer" | "refuse";
    verdict_hybrid: "answer" | "refuse";
    changed: boolean;
  }[];
};
```

- [ ] **Step 3: `components/admin/TrendChart.tsx`**

```tsx
"use client";

import type { InsightsSummary } from "@/lib/api";

const W = 640;
const H = 170;
const PAD = { l: 34, r: 40, t: 12, b: 24 };

/** Every calendar day from start to end inclusive, as YYYY-MM-DD in the browser's time zone. */
function daysBetween(start: string, end: string): string[] {
  const out: string[] = [];
  const d = new Date(`${start}T12:00:00`);
  const stop = new Date(`${end}T12:00:00`);
  while (d <= stop) {
    out.push(d.toLocaleDateString("en-CA"));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

/** Questions per day (bars, left axis) and median answer time (line, right axis). Missing days are zero. */
export function TrendChart({ days, data }: { days: number; data: InsightsSummary["per_day"] }) {
  if (data.length === 0) return <p className="muted">No questions in this period.</p>;
  const today = new Date().toLocaleDateString("en-CA");
  const start =
    days > 0
      ? (() => {
          const d = new Date();
          d.setDate(d.getDate() - (days - 1));
          return d.toLocaleDateString("en-CA");
        })()
      : data[0].day;
  const byDay = new Map(data.map((d) => [d.day, d]));
  const series = daysBetween(start, today).map((day) => ({ day, ...(byDay.get(day) ?? { questions: 0, median_ms: null }) }));

  const maxQ = Math.max(1, ...series.map((s) => s.questions));
  const maxS = Math.max(1, ...series.map((s) => (s.median_ms ?? 0) / 1000));
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const bw = iw / series.length;
  const x = (i: number) => PAD.l + i * bw;
  const yQ = (q: number) => PAD.t + ih - (q / maxQ) * ih;
  const yS = (s: number) => PAD.t + ih - (s / maxS) * ih;
  const line = series
    .map((s, i) => (s.median_ms === null ? null : `${x(i) + bw / 2},${yS(s.median_ms / 1000)}`))
    .filter(Boolean)
    .join(" ");
  const fmt = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

  return (
    <figure className="trend">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Questions per day and median answer time, ${fmt(series[0].day)} to ${fmt(today)}`}>
        <line className="axis" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + ih} y2={PAD.t + ih} />
        {series.map((s, i) => (
          <rect
            key={s.day}
            className="bar"
            x={x(i) + bw * 0.15}
            width={bw * 0.7}
            y={yQ(s.questions)}
            height={PAD.t + ih - yQ(s.questions)}
          >
            <title>{`${fmt(s.day)}: ${s.questions} question${s.questions === 1 ? "" : "s"}${s.median_ms === null ? "" : `, median ${(s.median_ms / 1000).toFixed(1)} s`}`}</title>
          </rect>
        ))}
        {line && <polyline className="latency" points={line} />}
        <text className="tick" x={PAD.l - 6} y={PAD.t + 4} textAnchor="end">{maxQ}</text>
        <text className="tick" x={PAD.l - 6} y={PAD.t + ih} textAnchor="end">0</text>
        <text className="tick latency-tick" x={W - PAD.r + 6} y={PAD.t + 4}>{maxS.toFixed(0)} s</text>
        <text className="tick" x={PAD.l} y={H - 6}>{fmt(series[0].day)}</text>
        <text className="tick" x={W - PAD.r} y={H - 6} textAnchor="end">{fmt(today)}</text>
      </svg>
      <figcaption>
        <span className="key bar-key" /> questions per day <span className="key line-key" /> median answer time
      </figcaption>
    </figure>
  );
}
```

- [ ] **Step 4: `components/admin/InsightsCard.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { TrendChart } from "@/components/admin/TrendChart";
import { type CompareResult, getJSON, type InsightsSummary, postJSON, type ProblemRow } from "@/lib/api";
import { openHref } from "@/lib/history";
import { moduleCode, tintVar } from "@/lib/modules";

const PERIODS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 0, label: "All" },
];
const KINDS = [
  { kind: "refused", label: "Refused" },
  { kind: "invalid", label: "Invalid citations" },
  { kind: "slow", label: "Slowest" },
] as const;
type Kind = (typeof KINDS)[number]["kind"];

const pct = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : "–");
const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);

/** What the query log says: volume, refusals, citations, speed, trend, problems, and dense vs hybrid. */
export function InsightsCard() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [days, setDays] = useState(7);
  const [kind, setKind] = useState<Kind>("refused");
  const [data, setData] = useState<{ key: string; s: InsightsSummary } | null>(null);
  const [rows, setRows] = useState<{ key: string; r: ProblemRow[] } | null>(null);
  const [error, setError] = useState(false);
  const [cmp, setCmp] = useState<CompareResult | null>(null);
  const [cmpBusy, setCmpBusy] = useState(false);
  const [cmpError, setCmpError] = useState<string | null>(null);

  const sKey = `${days}`;
  const pKey = `${days}:${kind}`;
  useEffect(() => {
    getJSON<InsightsSummary>(`/admin/insights?days=${days}&tz=${encodeURIComponent(tz)}`)
      .then((s) => setData({ key: `${days}`, s }))
      .catch(() => setError(true));
  }, [days, tz]);
  useEffect(() => {
    getJSON<ProblemRow[]>(`/admin/insights/problems?kind=${kind}&days=${days}&limit=20`)
      .then((r) => setRows({ key: `${days}:${kind}`, r }))
      .catch(() => setError(true));
  }, [days, kind]);

  async function runCompare() {
    setCmpBusy(true);
    setCmpError(null);
    try {
      setCmp(await postJSON<CompareResult>("/admin/compare", { limit: 20 }));
    } catch (e) {
      setCmpError((e as Error).message);
    } finally {
      setCmpBusy(false);
    }
  }

  const s = data?.key === sKey ? data.s : null;
  const problems = rows?.key === pKey ? rows.r : null;

  return (
    <section className="admin-card" aria-labelledby="insights-h">
      <header className="admin-card-head">
        <h2 id="insights-h">Insights</h2>
        <span className="tabs" role="tablist" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.days} type="button" role="tab" aria-selected={days === p.days} onClick={() => setDays(p.days)}>
              {p.label}
            </button>
          ))}
        </span>
      </header>

      {error && <p className="notice bad">Couldn&apos;t load the query log.</p>}
      {!s ? (
        <p className="muted">Reading the query log…</p>
      ) : (
        <>
          <dl className="kv">
            <dt>Questions</dt>
            <dd>{s.questions}</dd>
            <dt>Refused</dt>
            <dd>
              {s.refused} ({pct(s.refused, s.questions)}): not in your fiches
            </dd>
            <dt>Invalid citations</dt>
            <dd>
              {s.invalid} ({pct(s.invalid, s.questions)}){s.failed ? ` · ${s.failed} failed before answering` : ""}
            </dd>
            <dt>Answer time</dt>
            <dd>
              Median {secs(s.median_ms)}, slowest {secs(s.max_ms)}
            </dd>
          </dl>

          <h3>Trend</h3>
          <TrendChart days={days} data={s.per_day} />

          <h3>By module</h3>
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col">Module</th>
                <th scope="col">Questions</th>
                <th scope="col">Refused</th>
              </tr>
            </thead>
            <tbody>
              {s.per_module.map((m) => (
                <tr key={m.course ?? ""}>
                  <th scope="row">
                    <span className="label-card" style={{ "--tint": tintVar(m.course) } as React.CSSProperties}>
                      {m.course ? moduleCode(m.course) : "ALL"}
                    </span>{" "}
                    {m.course ?? "All drawers"}
                  </th>
                  <td>{m.questions}</td>
                  <td>{m.refused || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3>Problems</h3>
      <span className="tabs" role="tablist" aria-label="Problem kind">
        {KINDS.map((k) => (
          <button key={k.kind} type="button" role="tab" aria-selected={kind === k.kind} onClick={() => setKind(k.kind)}>
            {k.label}
          </button>
        ))}
      </span>
      {!problems ? (
        <p className="muted">Loading…</p>
      ) : problems.length === 0 ? (
        <p className="muted">None in this period.</p>
      ) : (
        <ul className="admin-list">
          {problems.map((p) => (
            <li key={p.id}>
              <Link className="admin-item problem-link" href={openHref(p.id, null)}>
                <strong dir="auto">{p.question}</strong>
                <span className="muted">
                  {p.course ?? "All drawers"} ·{" "}
                  {new Date(p.ts).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  {kind === "slow" ? ` · ${secs(p.latency_ms)}` : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <h3>Dense vs hybrid</h3>
      <p className="muted">
        Replays your 20 most recent distinct questions through both retrieval modes. It doesn&apos;t ask the model.
      </p>
      <p>
        <button type="button" className="quiet-btn" onClick={runCompare} disabled={cmpBusy}>
          {cmpBusy ? "Comparing…" : "Compare"}
        </button>
        {cmpError && <span className="action-note bad"> {cmpError}</span>}
      </p>
      {cmp && (
        <>
          <p>
            {cmp.summary.changed} of {cmp.summary.questions} questions would get different passages;{" "}
            {cmp.summary.flipped} would change between answering and refusing.
          </p>
          <ul className="admin-list compare">
            {cmp.rows
              .filter((r) => r.changed || r.verdict_dense !== r.verdict_hybrid)
              .map((r) => {
                const dense = new Set(r.dense.map((h) => h.chunk_id));
                const hybrid = new Set(r.hybrid.map((h) => h.chunk_id));
                return (
                  <li key={`${r.question}|${r.course}`}>
                    <span className="admin-item">
                      <strong dir="auto">{r.question}</strong>
                      <span className="muted">
                        {r.course ?? "All drawers"} · dense {r.verdict_dense}, hybrid {r.verdict_hybrid}
                      </span>
                      {r.hybrid
                        .filter((h) => !dense.has(h.chunk_id))
                        .map((h) => (
                          <span key={`+${h.chunk_id}`} className="diff add">
                            + {h.title} {h.label ?? `p. ${h.page}`}
                          </span>
                        ))}
                      {r.dense
                        .filter((h) => !hybrid.has(h.chunk_id))
                        .map((h) => (
                          <span key={`-${h.chunk_id}`} className="diff drop">
                            − {h.title} {h.label ?? `p. ${h.page}`}
                          </span>
                        ))}
                    </span>
                  </li>
                );
              })}
          </ul>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Page and CSS**

In `app/admin/page.tsx`, render `<InsightsCard />` between `<StatusCard />` and `<LibraryAdmin />` (health → usage → maintenance → configuration). Update the header subtitle to "The cabinet itself: services, usage, the index and settings".

Append to `app/globals.css`:

```css
/* ---- admin insights ---------------------------------------------------------------------- */
.tabs {
  display: inline-flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.tabs button {
  border: 1px solid transparent;
  border-radius: 4px;
  background: none;
  color: var(--muted);
  font: inherit;
  font-size: 0.84rem;
  padding: 0.2rem 0.6rem;
  cursor: pointer;
}

.tabs button[aria-selected="true"] {
  border-color: var(--rule-blue);
  background: var(--card-2);
  color: var(--ink);
}

.trend {
  margin: 0;
}

.trend svg {
  width: 100%;
  height: auto;
  display: block;
}

.trend .axis {
  stroke: var(--rule-blue);
}

.trend .bar {
  fill: var(--tint-modeling);
}

.trend .latency {
  fill: none;
  stroke: var(--primary);
  stroke-width: 2;
  stroke-linejoin: round;
}

.trend .tick {
  font-size: 11px;
  fill: var(--muted);
  font-variant-numeric: tabular-nums;
}

.trend .latency-tick {
  fill: var(--primary);
}

.trend figcaption {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--muted);
}

.key {
  display: inline-block;
  width: 0.9rem;
  height: 0.6rem;
  border-radius: 2px;
}

.bar-key {
  background: var(--tint-modeling);
}

.line-key {
  height: 2px;
  background: var(--primary);
  margin-inline-start: 0.6rem;
}

.problem-link {
  color: inherit;
  text-decoration: none;
}

.problem-link:hover strong {
  color: var(--primary);
}

.diff {
  font-size: 0.84rem;
}

.diff.add {
  color: var(--good);
}

.diff.drop {
  color: var(--muted);
  text-decoration: line-through;
}
```

The chart's colours must be checked against the `dataviz` rules from Step 1. If they call for a different contrast or mark weight, change these values instead of adding new ones.

- [ ] **Step 6: Typecheck, lint, commit**

Run: `npx tsc --noEmit && npm run lint`. Expected: clean.

```bash
git add frontend/lib/api.ts frontend/components/admin/TrendChart.tsx frontend/components/admin/InsightsCard.tsx frontend/app/admin/page.tsx frontend/app/globals.css
git commit -m "Admin page: insights with trend chart, problem lists and dense vs hybrid comparison"
```

---

### Task 5: Verify in the browser and polish

- [ ] **Step 1:** Restart the backend (`preview_start` "backend") and open `/admin`.
- [ ] **Step 2: Settings.**
  - Change "Passages per answer" to 4 and save. `config.local.yaml` should contain `top_k: 4`, and the source tag should read "set here".
  - Ask one question on the desk. Its `query_log.params->>'top_k'` is `4`.
  - Reset. The key leaves the file and the tag reads "config.yaml".
  - Enter 11: the error appears under the row, and nothing is written.
  - Delete that test question from History afterwards.
- [ ] **Step 3: Env lock.** Start `backend-test` (port 8001) with `TOP_K=6` added to its `env` in `.claude/launch.json` for this check only (revert after). Then `GET http://localhost:8001/admin/settings` shows `top_k` locked by `TOP_K`.
- [ ] **Step 4: Insights.**
  - Numbers and per-module counts match hand-run SQL over `query_log` for 7 days.
  - The trend shows a bar per day, with zero days drawn.
  - Problem tabs list rows, and one opens on the desk.
  - Compare returns in a few seconds with a sensible summary.
- [ ] **Step 5:** Console is clear of errors. Mobile width has no horizontal scroll, and the chart scales down.
- [ ] **Step 6: Impeccable polish pass** against `DESIGN.md`: one batched inspection round (desktop + mobile), one fix batch, then stop.
- [ ] **Step 7:** Run `cd backend && uv run pytest -q` (63 passed) and `cd frontend && npx tsc --noEmit && npm run lint`, then commit any polish.
