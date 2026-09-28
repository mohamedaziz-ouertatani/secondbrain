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
