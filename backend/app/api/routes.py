import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import get_pool
from ..ingest.pipeline import rescan
from ..llm import ollama
from ..rag.answer import ask

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    course: str | None = None


@router.post("/ask")
def ask_endpoint(req: AskRequest) -> StreamingResponse:
    def sse():
        for event, data in ask(req.question.strip(), req.course or None):
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/documents")
def documents() -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            """SELECT d.id, d.path, d.title, d.course, d.mime, d.page_count, d.status, d.error,
                      d.mtime, d.ingested_at, count(c.id) AS chunk_count
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.id ORDER BY d.course NULLS LAST, d.title"""
        ).fetchall()


@router.get("/courses")
def courses() -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT DISTINCT course FROM documents WHERE course IS NOT NULL ORDER BY course")
        return [r["course"] for r in rows]


@router.get("/files/{doc_id}")
def file(doc_id: int) -> FileResponse:
    with get_pool().connection() as conn:
        row = conn.execute("SELECT path, mime FROM documents WHERE id = %s", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(404, "document not found")
    inbox = get_settings().inbox
    path = (inbox / row["path"]).resolve()
    if not path.is_relative_to(inbox) or not path.is_file():
        raise HTTPException(404, "file not found")
    mime = "text/plain; charset=utf-8" if row["mime"].startswith("text/") else row["mime"]
    # inline so the browser PDF viewer opens it and honors #page=N
    return FileResponse(path, media_type=mime, content_disposition_type="inline", filename=Path(row["path"]).name)


_rescan_lock = threading.Lock()


@router.post("/ingest/rescan")
def rescan_endpoint() -> dict:
    if not _rescan_lock.acquire(blocking=False):
        raise HTTPException(409, "rescan already running")
    try:
        return rescan()
    finally:
        _rescan_lock.release()


@router.get("/health")
def health() -> dict:
    try:
        with get_pool().connection(timeout=3) as conn:
            conn.execute("SELECT 1")
        db = {"ok": True}
    except Exception as e:
        db = {"ok": False, "error": str(e)}
    oll = ollama.status()
    ok = db["ok"] and oll.get("reachable") and oll.get("llm_pulled") and oll.get("embed_pulled")
    return {"ok": bool(ok), "db": db, "ollama": oll, "inbox": str(get_settings().inbox)}
