import os
import time

from psycopg.types.json import Jsonb


def seed(db) -> list[int]:
    with db.get_pool().connection() as conn:
        ids = [conn.execute(
            """INSERT INTO query_log (question, params, retrieved, answer, citations, citation_valid, latency_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (q, Jsonb({"course": "Probability 2", "top_k": 5}), Jsonb([{"chunk_id": 1, "score": 0.61}]),
             f"Answer to {q} [1].", Jsonb([{"n": 1, "title": "Chap 1", "text": "Un vecteur gaussien…"}]), True, 4200),
        ).fetchone()["id"] for q in ("vecteur gaussien ?", "mouvement brownien ?", "loi de B_t ?")]
        conn.execute("INSERT INTO excluded_paths (path) VALUES ('Prob/old.pdf')")
    return ids


def rows(db):
    with db.get_pool().connection() as conn:
        return (conn.execute("SELECT * FROM query_log ORDER BY id").fetchall(),
                conn.execute("SELECT * FROM excluded_paths ORDER BY path").fetchall())


def test_backup_then_restore_brings_back_deleted_rows_exactly(env, tmp_path):
    from app.admin import backup

    _, db = env
    ids = seed(db)
    before = rows(db)
    f = backup.backup(tmp_path)
    assert f.name.startswith("secondbrain-") and f.name.endswith(".jsonl.gz")

    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM query_log WHERE id = ANY(%s)", (ids[:2],))
        conn.execute("DELETE FROM excluded_paths")
    r = backup.restore(f)
    assert (r["query_log"], r["excluded_paths"]) == (2, 1)
    assert rows(db) == before
    assert set(backup.restore(f).values()) == {0}  # nothing missing: nothing added

    with db.get_pool().connection() as conn:  # the id sequence moved past the restored rows
        new_id = conn.execute("INSERT INTO query_log (question) VALUES ('after restore') RETURNING id").fetchone()["id"]
    assert new_id > max(ids)


def test_prune_keeps_the_newest(tmp_path, monkeypatch):
    from app import config
    from app.admin import backup

    for day in range(1, 6):
        (tmp_path / f"secondbrain-2026-09-0{day}_030000.jsonl.gz").write_bytes(b"x")
    monkeypatch.setenv("BACKUP_KEEP", "3")
    config.get_settings.cache_clear()
    try:
        backup.prune(tmp_path)
    finally:
        config.get_settings.cache_clear()
    assert [p.name[12:22] for p in backup.backups(tmp_path)] == ["2026-09-03", "2026-09-04", "2026-09-05"]


def test_due_after_a_day(tmp_path):
    from app.admin import backup

    now = time.time()
    assert backup.due(now, tmp_path) is True  # never backed up
    f = tmp_path / "secondbrain-2026-09-28_030000.jsonl.gz"
    f.write_bytes(b"x")
    os.utime(f, (now - 2 * 3600, now - 2 * 3600))
    assert backup.due(now, tmp_path) is False
    os.utime(f, (now - 25 * 3600, now - 25 * 3600))
    assert backup.due(now, tmp_path) is True


def test_back_up_now_route_and_status(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.admin import backup
    from app.main import create_app

    _, db = env
    seed(db)
    monkeypatch.setattr(backup, "backup_dir", lambda: tmp_path)
    client = TestClient(create_app())
    r = client.post("/admin/backup")
    assert r.status_code == 200 and r.json()["rows"] == {"query_log": 3, "excluded_paths": 1, "eval_questions": 0, "eval_runs": 0, "tags": 0, "tag_aliases": 0, "planner_items": 0}
    last = client.get("/admin/status").json()["backup"]
    assert last["kept"] == 1 and last["bytes"] > 0 and last["name"] == r.json()["name"]


def test_tags_and_aliases_round_trip(env, tmp_path):
    from app.admin import backup

    _, db = env
    with db.get_pool().connection() as conn:
        t = conn.execute("INSERT INTO tags (course, name, user_named) VALUES ('C', 'kubernetes', true) RETURNING id").fetchone()["id"]
        conn.execute("INSERT INTO tag_aliases (course, raw, tag_id) VALUES ('C', 'k8s', %s), ('C', 'junk', NULL)", (t,))
    f = backup.backup(tmp_path)
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM tag_aliases")
    r = backup.restore(f)
    assert (r["tags"], r["tag_aliases"]) == (1, 2)

    with db.get_pool().connection() as conn:  # a tag recreated under another id: its alias is skipped, not fatal
        conn.execute("DELETE FROM tag_aliases")
        conn.execute("DELETE FROM tags")
        conn.execute("INSERT INTO tags (course, name) VALUES ('C', 'kubernetes')")
    r = backup.restore(f)
    assert (r["tags"], r["tag_aliases"]) == (0, 1)


def test_planner_items_round_trip(env, tmp_path):
    from app.admin import backup
    from app.planner.store import create_item

    _, db = env
    a = create_item({"kind": "note", "title": "idea", "body": "keep me"})
    f = backup.backup(tmp_path)
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM planner_items")
    assert backup.restore(f)["planner_items"] == 1
    b = create_item({"kind": "note", "title": "new"})
    assert b["id"] > a["id"]  # the sequence moved past restored ids
