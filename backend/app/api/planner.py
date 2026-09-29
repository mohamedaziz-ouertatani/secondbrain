"""Planner routes: notes, to-dos and events (app.planner)."""

from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..planner import file as notes_file
from ..planner import store
from ..planner.parse import parse_line

router = APIRouter(prefix="/planner")
Kind = Literal["note", "todo", "event"]


class ItemIn(BaseModel):
    kind: Kind
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=100_000)
    course: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool = False


class ItemPatch(BaseModel):
    """Only the fields sent are changed; null clears a date or the module."""

    kind: Kind | None = None
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=100_000)
    course: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    done: bool | None = None


class ParseIn(BaseModel):
    text: str = Field(max_length=500)
    course: str | None = None
    tz: str = "UTC"


def _modules() -> list[str]:
    inbox = get_settings().inbox
    return sorted(p.name for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []


def _found(row: dict | None) -> dict:
    if row is None:
        raise HTTPException(404, "item not found")
    return notes_file.reconcile(row)


@router.get("/items")
def items(kind: Kind | None = None, course: str | None = None,
          start: datetime | None = Query(None, alias="from"), end: datetime | None = Query(None, alias="to"),
          q: str | None = None, open: bool = False) -> list[dict]:
    rows = store.list_items(kind, course or None, start, end, (q or "").strip() or None, open)
    return [notes_file.reconcile(r) for r in rows]


@router.get("/upcoming")
def upcoming(course: str | None = None, days: int = Query(7, ge=1, le=60)) -> list[dict]:
    return store.upcoming(course or None, days)


@router.post("/items")
def create(body: ItemIn) -> dict:
    try:
        return store.create_item(body.model_dump())
    except store.PlannerError as e:
        raise HTTPException(422, str(e)) from None


@router.patch("/items/{item_id}")
def patch(item_id: int, body: ItemPatch) -> dict:
    fields = body.model_dump(include=body.model_fields_set)
    try:
        row = _found(store.update_item(item_id, fields))
    except store.PlannerError as e:
        raise HTTPException(422, str(e)) from None
    except store.Locked as e:
        raise HTTPException(409, str(e)) from None
    if row["filed_path"] and fields.keys() & {"title", "body"}:
        notes_file.rewrite(row)
    return row


@router.delete("/items/{item_id}", status_code=204)
def delete(item_id: int) -> Response:
    if not store.delete_item(item_id):
        raise HTTPException(404, "item not found")
    return Response(status_code=204)


@router.post("/parse")
def parse(body: ParseIn) -> dict:
    """A draft of what the line means; saves nothing. tz is the browser's zone, so "fri 23:59" is local."""
    try:
        zone = ZoneInfo(body.tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return parse_line(body.text, now=datetime.now(zone), modules=_modules(), course=body.course or None,
                      aliases=get_settings().planner_aliases)


@router.post("/items/{item_id}/file")
def file_note(item_id: int) -> dict:
    row = _found(store.get_item(item_id))
    if row["kind"] != "note":
        raise HTTPException(400, "only notes can be filed")
    if not row["course"]:
        raise HTTPException(400, "pick a drawer for this note first")
    if row["filed_path"]:
        return row
    return store.set_filed(item_id, notes_file.file_note(row))
