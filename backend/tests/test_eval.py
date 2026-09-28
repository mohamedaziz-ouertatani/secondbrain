import pytest
from fakes import fake_embed, words


def test_quotas_are_proportional_with_a_floor():
    from app.eval.generate import quotas

    q = quotas({"A": 100, "B": 10, "C": 3}, 30)
    assert sum(q.values()) == 30 and q["C"] == 3 and q["B"] >= 5 and q["A"] > q["B"]
    assert quotas({"A": 100, "B": 100}, 4) == {"A": 2, "B": 2}
    assert sum(quotas({"A": 3, "B": 2}, 50).values()) == 5  # never more than exists


def test_reject_reason():
    from app.eval.generate import reject_reason

    p = "Un vecteur gaussien est un vecteur aléatoire dont toute combinaison linéaire suit une loi normale."
    assert reject_reason("", p) == "empty"
    assert reject_reason("Vecteur gaussien ?", p) == "too short"
    assert reject_reason(" ".join(["mot"] * 41), p) == "too long"
    assert reject_reason("Est-ce que toute combinaison linéaire suit une loi normale ?", p) == "copies the passage"
    assert reject_reason("Qu'est-ce qui caractérise un vecteur gaussien ?", p) is None


def notes(inbox, n_courses=2, pages=4):
    """Markdown notes long enough (>= 60 tokens with the words counter), one page each."""
    for c in range(n_courses):
        for p in range(pages):
            f = inbox / f"Course{c}" / f"note{p}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(" ".join(f"topic{c}x{p} word{i}" for i in range(40)), encoding="utf-8")
    (inbox / "Course0" / "short.md").write_text("too short to ask about", encoding="utf-8")


def fake_chat(messages, schema, temperature=0.3):
    passage = messages[-1]["content"]
    token = next(w for w in passage.split() if w.startswith("topic"))
    return {"question": f"What should a student remember about {token} for the exam?"}


def test_generate_stores_questions_with_their_page(env):
    from app.eval.generate import generate
    from app.ingest.pipeline import rescan

    inbox, db = env
    notes(inbox)
    rescan(fake_embed, words)
    out = generate(n=6, chat=fake_chat)
    assert out["accepted"] == 6 and sum(out["per_course"].values()) == 6
    with db.get_pool().connection() as conn:
        rows = conn.execute("SELECT doc_path, page, question, course FROM eval_questions").fetchall()
    assert len(rows) == 6 and all(r["page"] == 1 and r["doc_path"].endswith(".md") for r in rows)
    assert not any(r["doc_path"].endswith("short.md") for r in rows)
    assert generate(n=6, chat=fake_chat)["accepted"] == 2  # only the 2 pages not asked about yet


def test_rank_and_metrics():
    from app.eval.run import metrics, rank_of, summarize

    hits = [{"path": "a.pdf", "page": 1}, {"path": "b.pdf", "page": 3}, {"path": "a.pdf", "page": 2}]
    assert rank_of(hits, {("a.pdf", 2)}) == 3 and rank_of(hits, {("z.pdf", 1)}) is None
    items = [
        {"source": "generated", "course": "A", "lang": "fr", "dense": {"rank": 1, "refused": False}, "hybrid": {"rank": 2, "refused": False}},
        {"source": "generated", "course": "A", "lang": "en", "dense": {"rank": 7, "refused": False}, "hybrid": {"rank": None, "refused": True}},
        {"source": "generated", "course": "B", "lang": "fr", "dense": {"rank": None, "refused": True}, "hybrid": {"rank": 1, "refused": False}},
    ]
    m = metrics(items, "dense")
    assert m["n"] == 3 and m["recall@1"] == pytest.approx(1 / 3) and m["recall@5"] == pytest.approx(1 / 3)
    assert m["recall@20"] == pytest.approx(2 / 3) and m["mrr"] == pytest.approx((1 + 1 / 7) / 3)
    assert m["refusal_rate"] == pytest.approx(1 / 3)
    s = summarize(items)
    assert set(s) == {"overall", "by_course", "by_lang", "by_source"} and s["by_course"]["B"]["hybrid"]["recall@1"] == 1


def seeded_embed(db):
    """An embedder that maps each eval question to its own page's vector, so the right page ranks first."""
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT q.question, c.embedding FROM eval_questions q
               JOIN documents d ON d.path = q.doc_path
               JOIN chunks c ON c.document_id = d.id AND c.page = q.page""").fetchall()
    table = {r["question"]: r["embedding"] for r in rows}
    return lambda texts: [table.get(t) if t in table else fake_embed([t])[0] for t in texts]


def test_retrieval_run_ranks_by_page_and_survives_reindex(env, monkeypatch):
    from app.eval import run
    from app.eval.generate import generate
    from app.ingest.pipeline import reindex, rescan

    inbox, db = env
    notes(inbox)
    rescan(fake_embed, words)
    generate(n=4, chat=fake_chat)
    monkeypatch.setattr(run.ollama, "embed", seeded_embed(db))
    run_id = run.run()
    with db.get_pool().connection() as conn:
        r = conn.execute("SELECT kind, metrics, per_question, params FROM eval_runs WHERE id = %s", (run_id,)).fetchone()
    assert r["kind"] == "retrieval" and r["params"]["questions"] == 4
    assert r["metrics"]["overall"]["dense"]["recall@1"] == 1.0
    assert all(q["dense"]["rank"] == 1 for q in r["per_question"])

    for c in ("Course0", "Course1"):  # new chunk ids, same pages
        reindex(course=c, embedder=fake_embed, counter=words)
    monkeypatch.setattr(run.ollama, "embed", seeded_embed(db))
    again = run.run()
    with db.get_pool().connection() as conn:
        m = conn.execute("SELECT metrics FROM eval_runs WHERE id = %s", (again,)).fetchone()["metrics"]
    assert m["overall"]["dense"]["recall@1"] == 1.0


def test_eval_routes_and_busy(env, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from app.eval import generate as gen
    from app.eval import jobs
    from app.ingest.pipeline import rescan
    from app.main import create_app

    inbox, _ = env
    notes(inbox)
    rescan(fake_embed, words)

    def slow_chat(messages, schema, temperature=0.3):
        time.sleep(0.3)
        return fake_chat(messages, schema)

    monkeypatch.setattr(gen.ollama, "chat_json", slow_chat)
    client = TestClient(create_app())
    assert client.post("/admin/eval/generate", json={"n": 3}).status_code == 202
    assert client.post("/admin/eval/run", json={"kind": "retrieval"}).status_code == 409
    jobs.wait(30)
    s = client.get("/admin/eval").json()
    assert s["questions"]["generated"] == 3 and s["job"]["state"] == "ok"
    monkeypatch.setattr("app.eval.run.ollama.embed", fake_embed)
    assert client.post("/admin/eval/run", json={"kind": "retrieval"}).status_code == 202
    jobs.wait(30)
    s = client.get("/admin/eval").json()
    assert s["latest"]["kind"] == "retrieval" and "dense" in s["latest"]["metrics"]["overall"]
    assert client.post("/admin/eval/cancel").status_code == 404
    assert client.post("/admin/eval/generate", json={"n": 0}).status_code == 422


def test_labelled_real_questions_join_the_evaluation(env):
    from psycopg.types.json import Jsonb

    from app.eval import jobs, run

    _, db = env
    cites = Jsonb([{"n": 1, "path": "Prob/a.md", "page": 1}, {"n": 2, "path": "Prob/b.md", "page": 3}])
    with db.get_pool().connection() as conn:
        good = conn.execute(
            """INSERT INTO query_log (question, params, citations, labels) VALUES (%s, %s, %s, %s) RETURNING id""",
            ("Qu'est-ce qu'un vecteur gaussien ?", Jsonb({"course": "Prob"}), cites,
             Jsonb({"relevant": {"1": True, "2": False}}))).fetchone()["id"]
        conn.execute("INSERT INTO query_log (question, citations, feedback) VALUES ('only a thumbs down', %s, -1)", (cites,))
    real = [q for q in run.questions() if q["source"] == "real"]
    assert [(q["id"], q["course"], q["truth"]) for q in real] == [(good, "Prob", {("Prob/a.md", 1)})]
    assert real[0]["lang"] == "fr"
    assert jobs.status()["questions"]["labelled"] == 1
