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
    Field("rerank", "Retrieval", "Reranker", "choice",
          "on: a cross-encoder on the GPU reorders the candidates before the top passages go to the model",
          options=("off", "on")),
    Field("top_k", "Retrieval", "Passages per answer", "int", "How many passages the model reads", 1, 10),
    Field("candidate_k", "Retrieval", "Candidates", "int",
          "Passages the reranker reorders, or taken from each list before hybrid fusion", 5, 100),
    Field("rrf_k", "Retrieval", "Fusion constant", "int", "Hybrid only: higher flattens the rank bonus", 1, 200),
    Field("min_score", "Retrieval", "Refusal threshold", "float", "Refuse unless a passage is at least this close", 0, 1),
    Field("doc_boost", "Retrieval", "Summary boost", "float",
          "Ranks passages higher when their file's summary matches the question; 0 is off", 0, 1),
    Field("llm_model", "Answers", "Model", "choice", "The model that writes answers; the next question loads it"),
    Field("temperature", "Answers", "Temperature", "float", "Lower is more literal", 0, 1.5),
    Field("doc_context", "Answers", "File context", "choice",
          "on: each passage the model reads starts with its file's summary", options=("off", "on")),
    Field("num_ctx", "Answers", "Context window", "int", "Tokens the model sees; larger uses more VRAM", 1024, 32768),
    Field("llm_keep_alive", "Answers", "Keep loaded for", "text",
          "After a question: 30m, 2h, 0 (unload at once) or -1 (never)", pattern=r"^(-1|0|\d+[smh])$"),
    Field("sync_auto_days", "Blackboard", "Automatic sync every", "int",
          "Days between automatic syncs; 0 turns them off", 0, 30),
)
FIELDS = {f.key: f for f in EDITABLE}
READONLY = {
    "embed_model": "Changing it means re-indexing everything",
    "embed_dim": "Changing it means re-indexing everything",
    "chunk_tokens": "Changing it means re-indexing everything",
    "chunk_overlap": "Changing it means re-indexing everything",
    "ocr_enabled": "Changing it means re-indexing everything",
    "ocr_min_words": "Changing it means re-indexing everything",
    "ocr_languages": "Changing it means re-indexing everything",
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
    elif f.control == "text" and (not isinstance(v, str) or (f.pattern and not re.fullmatch(f.pattern, v))):
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
        errors["candidate_k" if "candidate_k" in changes else "top_k"] = (
            "candidates per list can't be fewer than passages per answer")
    if errors:
        raise Invalid(errors)

    _write_local(new_local)
    if "rerank" in changes:
        from ..rag import rerank

        rerank.reranker.reset()  # a toggle retries a reranker that failed to load
    return view()
