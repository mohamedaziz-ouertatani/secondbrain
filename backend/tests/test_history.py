from psycopg.types.json import Jsonb


def add(db, question, course=None, answer="An answer [1].", citations=None):
    with db.get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO query_log (question, params, answer, citations, citation_valid, latency_ms)
               VALUES (%s, %s, %s, %s, true, 4200) RETURNING id""",
            (question, Jsonb({"course": course}), answer, Jsonb(citations or [{"n": 1, "text": "passage"}])),
        ).fetchone()["id"]


def test_newest_first_with_keyset_paging(env):
    from app.rag.history import list_history

    _, db = env
    ids = [add(db, f"q{i}") for i in range(5)]
    page = list_history(limit=2)
    assert [r["id"] for r in page] == [ids[4], ids[3]]
    assert [r["id"] for r in list_history(before=page[-1]["id"], limit=2)] == [ids[2], ids[1]]
    first = page[0]
    assert first["question"] == "q4" and first["course"] is None and first["latency_ms"] == 4200
    assert first["citations"] == [{"n": 1, "text": "passage"}] and first["citation_valid"] is True
    assert set(first) == {"id", "ts", "question", "course", "answer", "citations", "citation_valid", "latency_ms",
                          "feedback", "labels"}


def test_course_filter_search_and_limit_clamp(env):
    from app.rag.history import list_history

    _, db = env
    a = add(db, "Vecteur gaussien ?", course="Probability 2")
    b = add(db, "Transformers?", course="Advanced Deep Learning", answer="Attention is all you need.")
    c = add(db, "Growth of 50% per year", course="Probability 2", answer=None)
    assert [r["id"] for r in list_history(course="Probability 2")] == [c, a]
    assert [r["id"] for r in list_history(q="GAUSSIEN")] == [a]
    assert [r["id"] for r in list_history(q="attention")] == [b]  # matches the answer too
    assert [r["id"] for r in list_history(q="50%")] == [c]  # % is literal, not a wildcard
    assert list_history(q="_") == []  # so is _
    assert len(list_history(limit=0)) == 1
    assert len(list_history(limit=10_000)) == 3
    assert list_history(q="50%")[0]["answer"] is None


def test_routes_get_and_delete(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    _, db = env
    keep, gone = add(db, "keep me"), add(db, "delete me")
    client = TestClient(create_app())  # no `with`: the lifespan (watcher) doesn't start

    assert [r["id"] for r in client.get("/history", params={"limit": 5}).json()] == [gone, keep]
    assert client.get(f"/history/{keep}").json()["question"] == "keep me"
    assert client.delete(f"/history/{gone}").status_code == 204
    assert client.get(f"/history/{gone}").status_code == 404
    assert client.delete(f"/history/{gone}").status_code == 404
    assert [r["id"] for r in client.get("/history").json()] == [keep]
    # the browser deletes cross-origin
    pre = client.options(
        f"/history/{keep}",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "DELETE"},
    )
    assert pre.status_code == 200


def test_labels_merge_and_clear(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    _, db = env
    qid = add(db, "labelled question", citations=[{"n": 1, "path": "Prob/a.md", "page": 1},
                                                  {"n": 2, "path": "Prob/b.md", "page": 3}])
    client = TestClient(create_app())
    r = client.put(f"/history/{qid}/labels", json={"feedback": 1, "relevant": {"1": True, "2": False}})
    assert r.status_code == 200 and r.json()["feedback"] == 1
    assert r.json()["labels"] == {"relevant": {"1": True, "2": False}}
    r = client.put(f"/history/{qid}/labels", json={"relevant": {"2": None}})  # feedback absent: unchanged
    assert r.json()["feedback"] == 1 and r.json()["labels"] == {"relevant": {"1": True}}
    r = client.put(f"/history/{qid}/labels", json={"feedback": None, "relevant": {"1": None}})
    assert r.json()["feedback"] is None and r.json()["labels"] is None
    assert client.put("/history/999999/labels", json={"feedback": 1}).status_code == 404
    assert client.put(f"/history/{qid}/labels", json={"feedback": 2}).status_code == 422
    assert set(client.get(f"/history/{qid}").json()) >= {"feedback", "labels"}
