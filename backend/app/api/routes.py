import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import get_pool
from ..ingest.parse import parse
from ..ingest.pipeline import rescan
from ..llm import ollama
from ..rag.answer import ask
from ..rag.history import delete_history, get_history, list_history

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
                      d.mtime, d.ingested_at, d.first_seen, count(c.id) AS chunk_count
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.id ORDER BY d.course NULLS LAST, d.title"""
        ).fetchall()


@router.get("/courses")
def courses() -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT DISTINCT course FROM documents WHERE course IS NOT NULL ORDER BY course")
        return [r["course"] for r in rows]


@router.get("/history")
def history(course: str | None = None, q: str | None = None, before: int | None = None, limit: int = 50) -> list[dict]:
    return list_history(course or None, (q or "").strip() or None, before, limit)


@router.get("/history/{log_id}")
def history_item(log_id: int) -> dict:
    row = get_history(log_id)
    if not row:
        raise HTTPException(404, "message not found")
    return row


@router.delete("/history/{log_id}", status_code=204)
def history_delete(log_id: int) -> Response:
    if not delete_history(log_id):
        raise HTTPException(404, "message not found")
    return Response(status_code=204)


def _document_file(doc_id: int, columns: str = "path, mime") -> tuple[dict, Path]:
    """The document row and its file on disk; 404 unless the file sits inside the inbox."""
    with get_pool().connection() as conn:
        row = conn.execute(f"SELECT {columns} FROM documents WHERE id = %s", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(404, "document not found")
    inbox = get_settings().inbox
    path = (inbox / row["path"]).resolve()
    if not path.is_relative_to(inbox) or not path.is_file():
        raise HTTPException(404, "file not found")
    return row, path


@router.get("/documents/{doc_id}/pages")
def document_pages(doc_id: int) -> dict:
    """The document's text per page/slide/section, re-parsed from the file (no chunk overlap)."""
    row, path = _document_file(
        doc_id, "id, path, title, course, mime, page_count, status, error, ingested_at"
    )
    try:
        parsed = parse(path)
    except Exception as e:
        raise HTTPException(422, f"could not read {path.name}: {e}") from e
    labels = parsed.labels or [None] * len(parsed.pages)
    return {
        **row,
        "pages": [
            {"page": i, "label": label, "text": text}
            for i, (text, label) in enumerate(zip(parsed.pages, labels, strict=True), start=1)
        ],
    }


@router.get("/files/{doc_id}")
def file(doc_id: int) -> FileResponse:
    row, path = _document_file(doc_id)
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
