"""Planner items: notes, to-dos and events. Plain SQL over planner_items (migration 008)."""

from datetime import datetime, timedelta, timezone

from psycopg import errors

from ..db import get_pool
from ..rag.history import _contains

EDITABLE = ("kind", "title", "body", "course", "starts_at", "ends_at", "all_day")
BLACKBOARD_OWNED = {"kind", "title", "starts_at", "course"}  # the sync overwrites these
# When an item stops: its end, else its start; an all-day item lasts its whole day.
END = "COALESCE(ends_at, starts_at + CASE WHEN all_day THEN interval '1 day' ELSE interval '0' END)"
MESSAGES = {
    "planner_title_needed": "a to-do or event needs a title",
    "planner_note_undated": "a note has no date",
    "planner_done_on_todos": "only to-dos can be done",
    "planner_end_on_events": "only events have an end",
    "planner_event_start": "an event needs a start",
    "planner_end_after_start": "the end is before the start",
}


class PlannerError(ValueError):
    """A rule the item breaks, in words the UI can show (HTTP 422)."""


class Locked(PermissionError):
    """A change to a field that isn't yours to change (HTTP 409)."""


def _invalid(e: errors.CheckViolation) -> PlannerError:
    return PlannerError(MESSAGES.get(e.diag.constraint_name, "that item isn't valid"))


def create_item(fields: dict) -> dict:
    cols = [k for k in EDITABLE if k in fields]
    sql = (f"INSERT INTO planner_items ({', '.join(cols)}) "
           f"VALUES ({', '.join(f'%({c})s' for c in cols)}) RETURNING *")
    try:
        with get_pool().connection() as conn:
            return conn.execute(sql, fields).fetchone()
    except errors.CheckViolation as e:
        raise _invalid(e) from None


def get_item(item_id: int) -> dict | None:
    with get_pool().connection() as conn:
        return conn.execute("SELECT * FROM planner_items WHERE id = %s", (item_id,)).fetchone()


def update_item(item_id: int, fields: dict) -> dict | None:
    """Change only what differs. `done` (bool) sets or clears done_at."""
    try:
        with get_pool().connection() as conn, conn.transaction():
            row = conn.execute("SELECT * FROM planner_items WHERE id = %s FOR UPDATE", (item_id,)).fetchone()
            if row is None:
                return None
            changed = {k: v for k, v in fields.items() if k in EDITABLE and row[k] != v}
            if row["source"] == "blackboard" and changed.keys() & BLACKBOARD_OWNED:
                raise Locked("title, date and module follow Blackboard")
            if row["filed_path"] and changed.keys() & {"kind", "course"}:
                raise Locked("a filed note stays in its drawer: move the file instead")
            sets = [f"{k} = %({k})s" for k in changed]
            done = fields.get("done")
            if done is not None and (row["done_at"] is not None) != done:
                sets.append("done_at = now()" if done else "done_at = NULL")
            if not sets:
                return row
            return conn.execute(
                f"UPDATE planner_items SET {', '.join(sets)}, updated_at = now() WHERE id = %(id)s RETURNING *",
                {**changed, "id": item_id},
            ).fetchone()
    except errors.CheckViolation as e:
        raise _invalid(e) from None


def delete_item(item_id: int) -> bool:
    with get_pool().connection() as conn:
        return conn.execute("DELETE FROM planner_items WHERE id = %s", (item_id,)).rowcount > 0


def set_filed(item_id: int, path: str | None) -> dict | None:
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE planner_items SET filed_path = %s, updated_at = now() WHERE id = %s RETURNING *", (path, item_id)
        ).fetchone()


def list_items(kind: str | None = None, course: str | None = None, start: datetime | None = None,
               end: datetime | None = None, q: str | None = None, open_only: bool = False,
               limit: int = 1000) -> list[dict]:
    """Dated items by date, then undated ones newest first. start/end keep items overlapping [start, end)."""
    where, args = [], {"limit": max(1, min(limit, 1000))}
    if kind:
        where.append("kind = %(kind)s")
        args["kind"] = kind
    if course:
        where.append("course = %(course)s")
        args["course"] = course
    if start:
        where.append(f"{END} >= %(start)s")
        args["start"] = start
    if end:
        where.append("starts_at < %(end)s")
        args["end"] = end
    if q:
        where.append("(title ILIKE %(q)s OR body ILIKE %(q)s)")
        args["q"] = _contains(q)
    if open_only:
        where.append("done_at IS NULL")
    sql = "SELECT * FROM planner_items" + (" WHERE " + " AND ".join(where) if where else "")
    with get_pool().connection() as conn:
        return conn.execute(sql + " ORDER BY starts_at NULLS LAST, created_at DESC, id DESC LIMIT %(limit)s",
                            args).fetchall()


def upcoming(course: str | None = None, days: int = 7, now: datetime | None = None) -> list[dict]:
    """Open to-dos already due, plus anything not over yet that starts within `days`. Done and removed left out."""
    now = now or datetime.now(timezone.utc)
    args = {"now": now, "until": now + timedelta(days=days), "course": course}
    sql = f"""SELECT * FROM planner_items
              WHERE starts_at IS NOT NULL AND done_at IS NULL AND removed_at IS NULL
                AND ((kind = 'todo' AND starts_at < %(now)s) OR ({END} >= %(now)s AND starts_at < %(until)s))
                {"AND course = %(course)s" if course else ""}
              ORDER BY starts_at, id"""
    with get_pool().connection() as conn:
        return conn.execute(sql, args).fetchall()
