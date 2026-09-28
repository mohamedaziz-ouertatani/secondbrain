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
                      (SELECT count(*) FROM chunks WHERE (meta->>'ocr')::boolean) AS ocr_chunks,
                      pg_database_size(current_database()) AS db_bytes"""
        ).fetchone()


def _index_with_ocr() -> dict:
    from ..ingest import ocr

    idx = _index()
    return {**{k: v for k, v in idx.items() if k != "ocr_chunks"},
            "ocr": {"available": ocr.available(), "pages": idx["ocr_chunks"]}}


def _backup() -> dict | None:
    from . import backup

    return backup.last_backup()


def _safe(part):
    try:
        return part()
    except Exception:  # one broken part must not blank the page
        log.exception("status part %s failed", part.__name__)
        return None


def status() -> dict:
    return {
        "services": _safe(_services),
        "llm": _safe(_llm),
        "gpu": _safe(_gpu) or {"available": False},
        "answers": _safe(_answers),
        "index": _safe(_index_with_ocr),
        "backup": _safe(_backup),
    }
