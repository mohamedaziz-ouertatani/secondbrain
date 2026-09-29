"""Admin panel: system status and library maintenance (exclude, include, forced re-index)."""

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..admin import backup as backups
from ..admin import sync as sync_jobs
from ..admin.insights import compare, problems, summary
from ..admin.settings import Invalid, update, view
from ..admin.status import status
from ..config import get_settings
from ..db import get_pool
from ..enrich import vocab
from ..enrich.worker import worker as enricher
from ..eval import jobs as eval_jobs
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
        summary_errors = conn.execute(
            """SELECT id, path, title, course, enrich_error AS error FROM documents
               WHERE status = 'ok' AND enriched_sha = sha256 AND enrich_status = 'error'
               ORDER BY course NULLS LAST, title"""
        ).fetchall()
    return {
        "modules": modules,
        "problems": problems,
        "summary_errors": summary_errors,
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


@router.get("/settings")
def get_settings_view() -> dict:
    return view()


@router.put("/settings")
def put_settings(changes: dict[str, Any]) -> dict:
    try:
        return update(changes)
    except Invalid as e:
        raise HTTPException(422, e.errors) from e


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


class SyncBody(BaseModel):
    mode: Literal["sync", "preview", "probe"]
    course: str | None = None


@router.get("/sync")
def sync_status() -> dict:
    return sync_jobs.runner.status()


@router.post("/sync", status_code=202)
def sync_start(body: SyncBody) -> dict:
    if body.course is not None and body.course not in sync_jobs.modules():
        raise HTTPException(400, "no such module folder in the inbox")
    try:
        return sync_jobs.runner.start(body.mode, body.course)
    except sync_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sync/login", status_code=202)
def sync_login() -> dict:
    try:
        return sync_jobs.runner.start("login")
    except sync_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sync/cancel")
def sync_cancel() -> dict:
    job = sync_jobs.runner.cancel()
    if job is None:
        raise HTTPException(404, "no sync is running")
    return job


@router.post("/backup")
def backup_now() -> dict:
    f = backups.backup()
    return {**backups.last_backup(), "name": f.name, "rows": backups.counts_in(f)}


class GenerateBody(BaseModel):
    n: int = Field(150, ge=1, le=500)


class RunBody(BaseModel):
    kind: Literal["retrieval", "full"] = "retrieval"


@router.get("/eval")
def eval_status() -> dict:
    return eval_jobs.status()


@router.post("/eval/generate", status_code=202)
def eval_generate(body: GenerateBody) -> dict:
    try:
        return eval_jobs.start("generate", n=body.n)
    except eval_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/eval/run", status_code=202)
def eval_run(body: RunBody) -> dict:
    try:
        return eval_jobs.start(body.kind)
    except eval_jobs.Busy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/eval/cancel")
def eval_cancel() -> dict:
    job = eval_jobs.cancel()
    if job is None:
        raise HTTPException(404, "no evaluation job is running")
    return job


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
