"""Blackboard calendar items -> planner to-dos: windows, first import, re-sync, removed and back, dry run."""

from datetime import datetime, timedelta, timezone

from app.planner import blackboard as pb

NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
FOLDERS = {"_30051_1": "CSR", "_29474_1": "DEVOPS"}


def item(id_, cal, title, end, description=None):
    return {"id": id_, "calendarId": cal, "calendarName": "ESE: x", "title": title, "start": end, "end": end,
            "type": "GradebookColumn", "description": description}


class CalendarAPI:
    """Returns every item for every window: import_deadlines must de-duplicate by id."""

    def __init__(self, items):
        self.items, self.calls = items, []

    def get(self, path):
        self.calls.append(path)
        return {"results": list(self.items)}


def test_windows_cover_30_days_back_to_180_ahead_in_12_week_steps():
    w = pb.windows(NOW)
    assert w[0][0] == NOW - timedelta(days=30) and w[-1][1] == NOW + timedelta(days=180)
    assert len(w) == 3 and all(b - a <= timedelta(weeks=12) for a, b in w)
    assert all(w[i][1] == w[i + 1][0] for i in range(len(w) - 1))
    api = CalendarAPI([])
    pb.fetch(api, NOW)
    assert api.calls[0] == ("/learn/api/public/v1/calendars/items"
                            "?since=2026-08-30T12:00:00.000Z&until=2026-11-22T12:00:00.000Z")


def test_import_resync_removed_and_back(env):
    from app.planner.store import list_items, update_item

    items = [item("_1", "_30051_1", "Quiz", "2026-10-01T22:59:00.000Z", "<p>Chapter <b>2</b></p>"),
             item("_2", "_29474_1", "Jenkins CI", "2026-10-05T22:59:59.999Z"),
             item("_3", "_12670_1", "Old course", "2026-10-02T22:59:00.000Z")]  # not an inbox folder
    assert pb.import_deadlines(CalendarAPI(items), FOLDERS, now=NOW) == {
        "type": "deadlines", "new": 2, "updated": 0, "removed": 0}
    rows = {r["source_id"]: r for r in list_items()}
    assert set(rows) == {"_1", "_2"}
    q = rows["_1"]
    assert (q["kind"], q["course"], q["source"], q["title"], q["body"]) == (
        "todo", "CSR", "blackboard", "Quiz", "Chapter **2**")
    assert q["starts_at"] == datetime(2026, 10, 1, 22, 59, tzinfo=timezone.utc)
    update_item(q["id"], {"done": True, "body": "my notes"})

    moved = [item("_1", "_30051_1", "Quiz (moved)", "2026-10-08T22:59:00.000Z", "<p>new text</p>")]
    assert pb.import_deadlines(CalendarAPI(moved), FOLDERS, now=NOW) == {
        "type": "deadlines", "new": 0, "updated": 1, "removed": 1}  # _2 is gone from Blackboard
    rows = {r["source_id"]: r for r in list_items()}
    assert rows["_1"]["title"] == "Quiz (moved)" and rows["_1"]["body"] == "my notes"
    assert rows["_1"]["done_at"] is not None and rows["_2"]["removed_at"] is not None

    assert pb.import_deadlines(CalendarAPI(moved + items[1:]), FOLDERS, now=NOW) == {
        "type": "deadlines", "new": 0, "updated": 1, "removed": 0}  # _2 came back
    assert {r["source_id"]: r for r in list_items()}["_2"]["removed_at"] is None
    assert pb.import_deadlines(CalendarAPI(moved + items[1:]), FOLDERS, now=NOW) == {
        "type": "deadlines", "new": 0, "updated": 0, "removed": 0}


def test_removed_only_within_the_courses_fetched(env):
    from app.planner.store import list_items

    pb.import_deadlines(CalendarAPI([item("_1", "_30051_1", "Quiz", "2026-10-01T22:59:00.000Z")]), FOLDERS, now=NOW)
    ev = pb.import_deadlines(CalendarAPI([]), {"_29474_1": "DEVOPS"}, now=NOW)  # a --course DEVOPS sync
    assert ev["removed"] == 0 and list_items()[0]["removed_at"] is None


def test_dry_run_writes_nothing(env):
    from app.planner.store import list_items

    items = [item("_1", "_30051_1", "Quiz", "2026-10-01T22:59:00.000Z"),
             item("_3", "_x", "Other", "2026-10-01T22:59:00.000Z")]
    assert pb.import_deadlines(CalendarAPI(items), FOLDERS, dry_run=True, now=NOW) == {
        "type": "deadlines", "would_import": 1}
    assert list_items() == []
