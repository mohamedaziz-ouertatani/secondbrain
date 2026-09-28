from fakes import fake_embed, words
from psycopg.types.json import Jsonb


def log(db, question, course=None, answer="Answer [1].", valid=True, ms=5000, ts="now()"):
    with db.get_pool().connection() as conn:
        return conn.execute(
            f"""INSERT INTO query_log (ts, question, params, answer, citation_valid, latency_ms)
                VALUES ({ts}, %s, %s, %s, %s, %s) RETURNING id""",
            (question, Jsonb({"course": course}), answer, valid, ms),
        ).fetchone()["id"]


def test_summary_counts_medians_and_filters(env):
    from app.admin.insights import summary
    from app.llm.prompts import NOT_FOUND

    _, db = env
    log(db, "a", "Prob", ms=4000)
    log(db, "b", "Prob", answer=NOT_FOUND, valid=None, ms=1000)
    log(db, "c", None, valid=False, ms=9000)
    log(db, "d", None, answer=None, valid=None, ms=None)
    log(db, "old", "Prob", ms=60000, ts="now() - interval '40 days'")

    s = summary(7, "UTC")
    assert (s["questions"], s["refused"], s["invalid"], s["failed"]) == (4, 1, 1, 1)
    assert s["median_ms"] == 4000 and s["max_ms"] == 9000
    assert s["per_module"][0] == {"course": "Prob", "questions": 2, "refused": 1}
    assert summary(0, "UTC")["questions"] == 5 and summary(0, "UTC")["max_ms"] == 60000


def test_per_day_follows_the_time_zone(env):
    from app.admin.insights import summary

    _, db = env
    log(db, "late", ts="'2026-09-27 23:30:00+00'")  # 00:30 on the 28th in Tunis
    assert [d["day"] for d in summary(0, "UTC")["per_day"]] == ["2026-09-27"]
    assert [d["day"] for d in summary(0, "Africa/Tunis")["per_day"]] == ["2026-09-28"]


def test_problems_order(env):
    from app.admin.insights import problems
    from app.llm.prompts import NOT_FOUND

    _, db = env
    r1 = log(db, "r1", answer=NOT_FOUND, valid=None, ms=500)
    r2 = log(db, "r2", answer=NOT_FOUND, valid=None, ms=500)
    fast = log(db, "fast", ms=1000)
    slow = log(db, "slow", ms=90000)
    assert [p["id"] for p in problems("refused", 7, 50)] == [r2, r1]
    assert [p["id"] for p in problems("slow", 7, 2)] == [slow, fast]
    assert problems("invalid", 7, 50) == []


def test_routes_and_compare(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.admin import insights
    from app.ingest import pipeline
    from app.main import create_app

    inbox, db = env
    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    monkeypatch.setattr(insights.ollama, "embed", fake_embed)
    (inbox / "Prob").mkdir()
    (inbox / "Prob" / "g.md").write_text("Un vecteur gaussien a une fonction caractéristique. " * 20, encoding="utf-8")
    pipeline.rescan()
    log(db, "vecteur gaussien", "Prob")
    log(db, "vecteur gaussien", "Prob")  # duplicate: compared once
    log(db, "brownian motion", None)

    client = TestClient(create_app())
    assert client.get("/admin/insights", params={"days": 7, "tz": "Mars/Olympus"}).status_code == 400
    assert client.get("/admin/insights", params={"days": 7, "tz": "Africa/Tunis"}).json()["questions"] == 3
    assert client.get("/admin/insights/problems", params={"kind": "bogus"}).status_code == 422

    out = client.post("/admin/compare", json={"limit": 20}).json()
    assert out["summary"]["questions"] == 2
    row = out["rows"][0]
    assert set(row) == {"question", "course", "dense", "hybrid", "verdict_dense", "verdict_hybrid", "changed"}
    assert row["verdict_dense"] in ("answer", "refuse") and all("chunk_id" in h for h in row["dense"])
    assert client.post("/admin/compare", json={"limit": 0}).status_code == 422
