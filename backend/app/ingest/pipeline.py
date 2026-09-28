"""hash → parse → chunk → embed → upsert. One global lock: single-user app, keeps watcher and rescan from racing."""

import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama
from .chunk import TokenCounter, bge_m3_counter, chunk_pages
from .parse import SUPPORTED, parse

log = logging.getLogger(__name__)
_lock = threading.Lock()

# Bump when parsing/chunking changes so existing files get re-ingested on the next scan.
PARSER_VERSION = 3

Embedder = Callable[[list[str]], list]


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(get_settings().inbox).as_posix()


def course_of(rel: str) -> str | None:
    parts = rel.split("/")
    return parts[0] if len(parts) > 1 else None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED and not path.name.startswith(("~$", "."))


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

        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        doc = {"path": rel, "sha256": digest, "course": course_of(rel), "mtime": mtime,
               "title": path.stem, "mime": SUPPORTED[path.suffix.lower()], "page_count": 0,
               "status": "ok", "error": None, "parser_version": PARSER_VERSION}
        chunks, vectors, labels = [], [], None
        try:
            parsed = parse(path)
            doc.update(title=parsed.title, mime=parsed.mime, page_count=len(parsed.pages))
            labels = parsed.labels
            if not parsed.has_text:
                doc["status"] = "empty_text"
            else:
                chunks = chunk_pages(parsed.pages, counter or bge_m3_counter(), s.chunk_tokens, s.chunk_overlap)
                vectors = embedder([c.text for c in chunks])
        except Exception as e:
            log.exception("ingest failed: %s", rel)
            doc.update(status="error", error=f"{type(e).__name__}: {e}")
            chunks, vectors = [], []

        with get_pool().connection() as conn, conn.transaction():
            doc_id = conn.execute(
                """INSERT INTO documents (path, sha256, course, title, mime, page_count, status, error, mtime, parser_version, ingested_at)
                   VALUES (%(path)s, %(sha256)s, %(course)s, %(title)s, %(mime)s, %(page_count)s, %(status)s, %(error)s, %(mtime)s, %(parser_version)s, now())
                   ON CONFLICT (path) DO UPDATE SET sha256 = EXCLUDED.sha256, course = EXCLUDED.course,
                     title = EXCLUDED.title, mime = EXCLUDED.mime, page_count = EXCLUDED.page_count,
                     status = EXCLUDED.status, error = EXCLUDED.error, mtime = EXCLUDED.mtime,
                     parser_version = EXCLUDED.parser_version, ingested_at = now()
                   RETURNING id""",
                doc,
            ).fetchone()["id"]
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
            if chunks:
                meta = {"source": rel, "course": doc["course"], "mtime": mtime.isoformat()}
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks (document_id, ord, page, text, n_tokens, embedding, meta) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [(doc_id, i, c.page, c.text, c.n_tokens, v,
                          Jsonb({**meta, "label": labels[c.page - 1]} if labels else meta))
                         for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))],
                    )
        log.info("ingested %s: %s, %d chunks", rel, doc["status"], len(chunks))
        return doc["status"]


def remove_file(path: Path) -> bool:
    rel = rel_path(path)
    with _lock, get_pool().connection() as conn:
        n = conn.execute("DELETE FROM documents WHERE path = %s", (rel,)).rowcount
    if n:
        log.info("removed %s", rel)
    return bool(n)


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


def rescan(embedder: Embedder | None = None, counter: TokenCounter | None = None) -> dict[str, int]:
    """Ingest new/changed files and drop documents whose file is gone."""
    inbox = get_settings().inbox
    inbox.mkdir(parents=True, exist_ok=True)
    stats: dict[str, int] = {}
    seen: set[str] = set()
    for p in sorted(inbox.rglob("*")):
        if p.is_file() and is_supported(p):
            result = ingest_file(p, embedder, counter)
            if result != "excluded":  # an excluded file counts as gone, so a stale row is dropped
                seen.add(rel_path(p))
            stats[result] = stats.get(result, 0) + 1
    with _lock, get_pool().connection() as conn:
        paths = [r["path"] for r in conn.execute("SELECT path FROM documents")]
        gone = [p for p in paths if p not in seen]
        if gone:
            conn.execute("DELETE FROM documents WHERE path = ANY(%s)", (gone,))
    stats["removed"] = len(gone)
    return stats
