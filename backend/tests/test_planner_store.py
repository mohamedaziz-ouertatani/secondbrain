"""Planner items in Postgres: the rules the table enforces, lists, upcoming, and what Blackboard owns."""

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def mk(**f):
    from app.planner.store import create_item

    return create_item({"title": "x", **f})


@pytest.mark.parametrize("fields,message", [
    ({"kind": "note", "title": "n", "starts_at": NOW}, "a note has no date"),
    ({"kind": "event", "title": "e"}, "an event needs a start"),
    ({"kind": "todo", "title": ""}, "a to-do or event needs a title"),
    ({"kind": "todo", "title": "t", "starts_at": NOW, "ends_at": NOW + timedelta(hours=1)}, "only events have an end"),
    ({"kind": "event", "title": "e", "starts_at": NOW, "ends_at": NOW - timedelta(hours=1)},
     "the end is before the start"),
])
def test_rules_come_back_in_words(env, fields, message):
    from app.planner.store import PlannerError, create_item

    with pytest.raises(PlannerError, match=message):
        create_item(fields)


def test_list_filters_and_order(env):
    from app.planner.store import list_items, update_item

    a = mk(kind="todo", title="Jenkins pipeline", starts_at=NOW + timedelta(days=1), course="DEVOPS")
    b = mk(kind="event", title="exam", starts_at=NOW + timedelta(days=5), ends_at=NOW + timedelta(days=5, hours=2))
    n = mk(kind="note", title="idea", body="spend 50% of the time on CI")
    t = mk(kind="todo", title="undated")
    assert [r["id"] for r in list_items()] == [a["id"], b["id"], t["id"], n["id"]]  # dated first, then newest
    assert [r["id"] for r in list_items(start=NOW + timedelta(days=2), end=NOW + timedelta(days=6))] == [b["id"]]
    assert [r["id"] for r in list_items(q="50%")] == [n["id"]]  # % is literal
    assert [r["id"] for r in list_items(kind="todo", course="DEVOPS")] == [a["id"]]
    update_item(a["id"], {"done": True})
    assert a["id"] not in [r["id"] for r in list_items(open_only=True)]


def test_upcoming_is_overdue_plus_the_window(env):
    from app.planner.store import update_item, upcoming

    _, db = env
    overdue = mk(kind="todo", title="late", starts_at=NOW - timedelta(days=2))
    allday = mk(kind="event", title="today", starts_at=NOW - timedelta(hours=10), all_day=True)
    soon = mk(kind="event", title="exam", starts_at=NOW + timedelta(days=3), course="Probability 2")
    mk(kind="todo", title="far", starts_at=NOW + timedelta(days=20))
    mk(kind="event", title="over", starts_at=NOW - timedelta(days=1))
    mk(kind="note", title="n")
    done = mk(kind="todo", title="done", starts_at=NOW + timedelta(days=1))
    update_item(done["id"], {"done": True})
    gone = mk(kind="todo", title="gone", starts_at=NOW + timedelta(days=1))
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE planner_items SET removed_at = now() WHERE id = %s", (gone["id"],))

    assert [r["id"] for r in upcoming(now=NOW)] == [overdue["id"], allday["id"], soon["id"]]
    assert [r["id"] for r in upcoming(course="Probability 2", now=NOW)] == [soon["id"]]


def test_done_and_what_blackboard_owns(env):
    from app.planner.store import Locked, PlannerError, update_item

    _, db = env
    t = mk(kind="todo", title="t")
    assert update_item(t["id"], {"done": True})["done_at"] is not None
    assert update_item(t["id"], {"done": False})["done_at"] is None
    e = mk(kind="event", title="e", starts_at=NOW)
    with pytest.raises(PlannerError, match="only to-dos can be done"):
        update_item(e["id"], {"done": True})
    assert update_item(999_999, {"title": "x"}) is None

    with db.get_pool().connection() as conn:
        bb = conn.execute(
            """INSERT INTO planner_items (kind, title, course, starts_at, source, source_id)
               VALUES ('todo', 'Quiz', 'CSR', %s, 'blackboard', '_1_1') RETURNING id""", (NOW,)).fetchone()["id"]
    with pytest.raises(Locked, match="follow Blackboard"):
        update_item(bb, {"title": "Mine"})
    r = update_item(bb, {"title": "Quiz", "body": "my notes", "done": True})  # an unchanged title is fine
    assert r["body"] == "my notes" and r["done_at"] is not None


def test_filed_note_keeps_its_drawer(env):
    from app.planner.store import Locked, set_filed, update_item

    n = mk(kind="note", title="CI", course="DEVOPS")
    assert set_filed(n["id"], "DEVOPS/CI.md")["filed_path"] == "DEVOPS/CI.md"
    with pytest.raises(Locked, match="stays in its drawer"):
        update_item(n["id"], {"course": "CSR"})
    assert update_item(n["id"], {"body": "Jenkins"})["body"] == "Jenkins"
    assert set_filed(n["id"], None)["filed_path"] is None
