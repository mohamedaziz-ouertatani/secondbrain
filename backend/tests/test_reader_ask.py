"""Asking from the reader: answers can be kept to the open document."""

from fakes import fake_embed, words


def _two_files(env):
    from app.ingest.pipeline import rescan

    inbox, db = env
    (inbox / "ML").mkdir(parents=True)
    (inbox / "ML" / "descent.md").write_text("Gradient descent takes steps against the gradient. " * 40, encoding="utf-8")
    (inbox / "ML" / "trees.md").write_text("A decision tree splits on the feature with most information gain. " * 40,
                                           encoding="utf-8")
    rescan(fake_embed, words)
    with db.get_pool().connection() as conn:
        ids = {r["path"]: r["id"] for r in conn.execute("SELECT id, path FROM documents").fetchall()}
        # a question that sits right on top of the *other* file's first chunk
        qvec = conn.execute(
            "SELECT embedding FROM chunks WHERE document_id = %s ORDER BY id LIMIT 1", (ids["ML/trees.md"],)
        ).fetchone()["embedding"]
    return ids, qvec


def test_retrieval_keeps_to_one_document(env):
    from app.rag.retrieve import retrieve_with_vector

    ids, qvec = _two_files(env)
    descent = ids["ML/descent.md"]
    for mode in ("dense", "hybrid"):
        candidates, _ = retrieve_with_vector(qvec, "decision tree gradient", mode=mode, rerank=False)
        assert {h["doc_id"] for h in candidates} == set(ids.values())  # unscoped: both files
        candidates, _ = retrieve_with_vector(qvec, "decision tree gradient", mode=mode, rerank=False, doc_id=descent)
        assert candidates and {h["doc_id"] for h in candidates} == {descent}


def test_ask_scoped_to_a_document_cites_it_and_logs_it(env, monkeypatch):
    from app.config import get_settings
    from app.rag import answer, retrieve

    ids, qvec = _two_files(env)
    descent = ids["ML/descent.md"]
    monkeypatch.setenv("MIN_SCORE", "-1")  # fake vectors: let anything through
    get_settings.cache_clear()
    monkeypatch.setattr(retrieve.ollama, "embed", lambda texts: [qvec])
    monkeypatch.setattr(answer.ollama, "chat_stream", lambda messages: iter(["It steps downhill [1]."]))

    done = dict(list(answer.ask("how does it step?", "ML", doc_id=descent)))["done"]
    assert done["citations"] and {c["doc_id"] for c in done["citations"]} == {descent}
    _, db = env
    with db.get_pool().connection() as conn:
        params = conn.execute("SELECT params FROM query_log WHERE id = %s", (done["log_id"],)).fetchone()["params"]
    assert params["doc_id"] == descent and params["course"] == "ML"


def test_ask_endpoint_passes_the_document(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import create_app

    seen = {}

    def fake_ask(question, course=None, doc_id=None):
        seen.update(course=course, doc_id=doc_id)
        yield "done", {"answer": "", "citations": [], "citation_valid": None, "log_id": None}

    monkeypatch.setattr(routes, "ask", fake_ask)
    res = TestClient(create_app()).post("/ask", json={"question": "q", "course": "ML", "doc_id": 7})
    assert res.status_code == 200 and seen == {"course": "ML", "doc_id": 7}
