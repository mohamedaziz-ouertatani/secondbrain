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
            chunks = conn.execute(
                "SELECT text, n_tokens FROM chunks WHERE document_id = %s ORDER BY ord", (doc["id"],)
            ).fetchall() if doc else []
        if doc is None:
            return False
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
