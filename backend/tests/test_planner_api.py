"""Planner routes: CRUD, the rules as 422/409, parsing with the inbox's modules, filing notes into the inbox."""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())  # no `with`: no watcher or background workers


def test_create_list_patch_delete(client):
    r = client.post("/planner/items", json={"kind": "todo", "title": "Jenkins CI", "course": "DEVOPS",
                                            "starts_at": "2026-10-02T23:59:00+01:00"})
    assert r.status_code == 200
    item = r.json()
    assert datetime.fromisoformat(item["starts_at"]) == datetime(2026, 10, 2, 22, 59, tzinfo=timezone.utc)
    assert item["source"] == "me"
    assert [i["id"] for i in client.get("/planner/items", params={"course": "DEVOPS"}).json()] == [item["id"]]
    assert client.get("/planner/items", params={"course": "CSR"}).json() == []

    r = client.patch(f"/planner/items/{item['id']}", json={"done": True})
    assert r.json()["done_at"] is not None
    assert client.get("/planner/items", params={"open": "true"}).json() == []

    assert client.delete(f"/planner/items/{item['id']}").status_code == 204
    assert client.delete(f"/planner/items/{item['id']}").status_code == 404
    assert client.patch(f"/planner/items/{item['id']}", json={"title": "x"}).status_code == 404


def test_rules_are_422_and_blackboard_fields_409(env, client):
    r = client.post("/planner/items", json={"kind": "event", "title": "exam"})
    assert r.status_code == 422 and r.json()["detail"] == "an event needs a start"
    n = client.post("/planner/items", json={"kind": "note", "title": "idea"}).json()
    r = client.patch(f"/planner/items/{n['id']}", json={"starts_at": "2026-10-02T09:00:00Z"})
    assert r.status_code == 422 and r.json()["detail"] == "a note has no date"

    _, db = env
    with db.get_pool().connection() as conn:
        bb = conn.execute("""INSERT INTO planner_items (kind, title, course, starts_at, source, source_id)
                             VALUES ('todo', 'Quiz', 'CSR', now(), 'blackboard', '_9_1') RETURNING id""").fetchone()["id"]
    assert client.patch(f"/planner/items/{bb}", json={"title": "Mine"}).status_code == 409
    assert client.patch(f"/planner/items/{bb}", json={"body": "read ch. 2", "done": True}).status_code == 200


def test_parse_uses_inbox_modules_and_the_browser_zone(env, client):
    inbox, _ = env
    (inbox / "DEVOPS").mkdir()
    r = client.post("/planner/parse", json={"text": "DEVOPS TP due fri 23:59", "tz": "Africa/Tunis"}).json()
    assert r["kind"] == "todo" and r["course"] == "DEVOPS" and r["title"] == "DEVOPS TP"
    assert r["starts_at"].endswith("T23:59:00+01:00")
    r = client.post("/planner/parse", json={"text": "check the slides", "course": "CSR", "tz": "Not/AZone"})
    assert r.status_code == 200 and r.json()["course"] == "CSR" and r.json()["kind"] == "note"


def test_upcoming_route(client):
    client.post("/planner/items", json={"kind": "todo", "title": "late", "starts_at": "2020-01-01T10:00:00Z"})
    client.post("/planner/items", json={"kind": "note", "title": "n"})
    assert [i["title"] for i in client.get("/planner/upcoming").json()] == ["late"]
    assert client.get("/planner/upcoming", params={"days": 0}).status_code == 422


def test_file_into_drawer(env, client):
    inbox, _ = env
    n = client.post("/planner/items", json={"kind": "note", "title": "CI notes", "body": "Jenkins stages",
                                            "course": "DEVOPS"}).json()
    r = client.post(f"/planner/items/{n['id']}/file")
    assert r.status_code == 200 and r.json()["filed_path"] == "DEVOPS/CI notes.md"
    assert (inbox / "DEVOPS" / "CI notes.md").read_text(encoding="utf-8") == "# CI notes\n\nJenkins stages\n"

    twin = client.post("/planner/items", json={"kind": "note", "title": "CI notes", "course": "DEVOPS"}).json()
    assert client.post(f"/planner/items/{twin['id']}/file").json()["filed_path"] == "DEVOPS/CI notes (2).md"

    client.patch(f"/planner/items/{n['id']}", json={"body": "Jenkins stages and agents"})
    assert (inbox / "DEVOPS" / "CI notes.md").read_text(encoding="utf-8").endswith("stages and agents\n")
    assert client.patch(f"/planner/items/{n['id']}", json={"course": "CSR"}).status_code == 409

    (inbox / "DEVOPS" / "CI notes.md").unlink()
    items = {i["id"]: i for i in client.get("/planner/items").json()}
    assert items[n["id"]]["filed_path"] is None and items[n["id"]]["body"] == "Jenkins stages and agents"


def test_file_needs_a_note_with_a_drawer(client):
    t = client.post("/planner/items", json={"kind": "todo", "title": "t", "course": "DEVOPS"}).json()
    assert client.post(f"/planner/items/{t['id']}/file").status_code == 400
    n = client.post("/planner/items", json={"kind": "note", "title": "loose"}).json()
    r = client.post(f"/planner/items/{n['id']}/file")
    assert r.status_code == 400 and r.json()["detail"] == "pick a drawer for this note first"
