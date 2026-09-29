"""Blackboard's calendar -> planner to-dos. It only holds gradebook due dates (probe, 2026-09-29):
no exams and no class times, so those are typed by hand."""

from datetime import datetime, timedelta, timezone

from markdownify import markdownify

from ..db import get_pool

CALENDAR = "/learn/api/public/v1/calendars/items"
BACK, AHEAD = timedelta(days=30), timedelta(days=180)
STEP = timedelta(weeks=12)  # Blackboard answers 400 to a 7-month window; ~3 months works


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def windows(now: datetime) -> list[tuple[datetime, datetime]]:
    start, end, out = now - BACK, now + AHEAD, []
    while start < end:
        stop = min(start + STEP, end)
        out.append((start, stop))
        start = stop
    return out


def fetch(api, now: datetime) -> list[dict]:
    items: dict[str, dict] = {}
    for a, b in windows(now):
        for it in api.get(f"{CALENDAR}?since={_iso(a)}&until={_iso(b)}").get("results", []):
            items[it["id"]] = it  # an item on a window edge comes back twice
    return list(items.values())


def to_rows(items: list[dict], folders: dict[str, str]) -> list[dict]:
    """One to-do per item of a synced course; the due time is the item's end."""
    rows = []
    for it in items:
        folder = folders.get(it.get("calendarId"))
        due = it.get("end") or it.get("start")
        if not folder or not due or not (it.get("title") or "").strip():
            continue
        rows.append({
            "source_id": it["id"], "title": it["title"].strip(), "course": folder,
            "starts_at": datetime.fromisoformat(due.replace("Z", "+00:00")),
            "body": markdownify(it["description"]).strip() if it.get("description") else "",
        })
    return rows


def upsert(rows: list[dict], courses: set[str], since: datetime, until: datetime, now: datetime) -> dict:
    """Title, date and module follow Blackboard; body is only set on insert, done_at is never touched.
    An item of a fetched course, due inside the fetched window, that Blackboard no longer returns is
    marked removed, not deleted."""
    new = updated = 0
    with get_pool().connection() as conn, conn.transaction():
        for r in rows:
            hit = conn.execute(
                """INSERT INTO planner_items (kind, title, body, course, starts_at, source, source_id)
                   VALUES ('todo', %(title)s, %(body)s, %(course)s, %(starts_at)s, 'blackboard', %(source_id)s)
                   ON CONFLICT (source, source_id) DO UPDATE
                       SET title = EXCLUDED.title, course = EXCLUDED.course, starts_at = EXCLUDED.starts_at,
                           removed_at = NULL, updated_at = now()
                       WHERE (planner_items.title, planner_items.course, planner_items.starts_at,
                              planner_items.removed_at IS NULL)
                             IS DISTINCT FROM (EXCLUDED.title, EXCLUDED.course, EXCLUDED.starts_at, true)
                   RETURNING (xmax = 0) AS inserted""", r).fetchone()
            if hit:
                new += hit["inserted"]
                updated += not hit["inserted"]
        removed = conn.execute(
            """UPDATE planner_items SET removed_at = %s, updated_at = now()
               WHERE source = 'blackboard' AND removed_at IS NULL AND course = ANY(%s::text[])
                 AND starts_at >= %s AND starts_at < %s AND NOT (source_id = ANY(%s::text[]))""",
            (now, list(courses), since, until, [r["source_id"] for r in rows])).rowcount
    return {"new": new, "updated": updated, "removed": removed}


def import_deadlines(api, folders: dict[str, str], dry_run: bool = False, now: datetime | None = None) -> dict:
    """`folders` maps the synced courses' ids (== calendarId) to their inbox folders."""
    now = now or datetime.now(timezone.utc)
    w = windows(now)
    rows = to_rows(fetch(api, now), folders)
    if dry_run:
        return {"type": "deadlines", "would_import": len(rows)}
    return {"type": "deadlines", **upsert(rows, set(folders.values()), w[0][0], w[-1][1], now)}
