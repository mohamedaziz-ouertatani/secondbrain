import threading
import time

import numpy as np
import pytest
from fakes import fake_embed, words
from psycopg.types.json import Jsonb


def test_migration_adds_enrichment_columns_and_tag_tables(env):
    _, db = env
    with db.get_pool().connection() as conn:
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'")}
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    assert {"summary", "concepts", "raw_tags", "enriched_sha", "enrich_status", "enrich_error",
            "summary_embedding"} <= cols
    assert "tags" not in cols
    assert {"tags", "tag_aliases", "document_tags"} <= tables


def test_ask_marks_answering_until_the_stream_ends_or_is_closed(env, monkeypatch):
    from app.llm import busy
    from app.rag import answer

    monkeypatch.setattr(answer, "retrieve", lambda q, c, **kw: ([], []))  # refused: no LLM call
    gen = answer.ask("anything?")
    assert not busy.is_answering()
    next(gen)
    assert busy.is_answering()
    list(gen)
    assert not busy.is_answering()

    gen = answer.ask("again?")
    next(gen)
    gen.close()  # the client went away mid-stream
    assert not busy.is_answering()


def test_save_local_writes_one_key(tmp_path, monkeypatch):
    from app import config
    from app.admin import settings

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    settings.save_local("enrich_paused", True)
    assert config.get_settings().enrich_paused is True
    settings.save_local("enrich_paused", False)
    assert config.get_settings().enrich_paused is False
    config.get_settings.cache_clear()


GOOD = {"summary": "Un résumé.", "concepts": ["Gradient descent", "gradient descent", " Loss ", ""],
        "tags": ["Optimization", "optimization", "  Stochastic   GD ", "x" * 41]}


def recording_chat(calls, reply=None):
    def chat(messages, schema, temperature=0.3):
        calls.append(messages)
        return reply(len(calls)) if reply else {**GOOD, "summary": f"Summary {len(calls)}."}
    return chat


def test_groups_respect_the_budget_and_never_split_a_chunk():
    from app.enrich.summarise import groups

    chunks = [{"text": "x", "n_tokens": n} for n in (1000, 1000, 600, 2600, 100)]
    assert [[c["n_tokens"] for c in g] for g in groups(chunks, budget=2500)] == [[1000, 1000], [600], [2600], [100]]
    assert groups([]) == []


def test_clean_trims_dedupes_and_lowercases_tags():
    from app.enrich.summarise import clean

    assert clean(GOOD) == {"summary": "Un résumé.", "concepts": ["Gradient descent", "Loss"],
                           "tags": ["optimization", "stochastic gd"]}


def test_short_file_is_one_call():
    from app.enrich.summarise import summarise

    calls = []
    out = summarise("Chap 1", [{"text": "Le gradient est un vecteur de dérivées partielles.", "n_tokens": 300}],
                    recording_chat(calls))
    assert len(calls) == 1 and out["summary"] == "Summary 1."
    assert "French" in calls[0][0]["content"] and "Chap 1" in calls[0][1]["content"]


def test_long_file_maps_then_reduces():
    from app.enrich.summarise import summarise

    calls = []
    summarise("Deck", [{"text": "the cluster runs pods", "n_tokens": 2000} for _ in range(3)], recording_chat(calls))
    assert len(calls) == 4
    assert "Part 1 of 3" in calls[0][1]["content"] and "Part 3 of 3" in calls[2][1]["content"]
    assert "Summary 1." in calls[3][1]["content"] and "Summary 3." in calls[3][1]["content"]


def test_many_parts_reduce_in_rounds():
    from app.enrich.summarise import summarise

    calls = []
    summarise("Deck", [{"text": "slide", "n_tokens": 2500} for _ in range(20)], recording_chat(calls))
    assert len(calls) == 20 + 3 + 1  # 20 maps, then ceil(20/8) = 3 reductions, then 1


def test_bad_output_is_retried_once_then_raises():
    from app.enrich.summarise import BadOutput, summarise

    one = [{"text": "text", "n_tokens": 10}]
    calls = []
    out = summarise("F", one, recording_chat(calls, lambda n: {"summary": ""} if n == 1 else GOOD))
    assert len(calls) == 2 and "JSON only" in calls[1][0]["content"] and out["summary"] == "Un résumé."

    with pytest.raises(BadOutput):
        summarise("F", one, recording_chat([], lambda n: {"summary": "no lists"}))


def add_doc(db, path, course="Course0", sha="a", status="ok", texts=("Le gradient est un vecteur.",)):
    with db.get_pool().connection() as conn:
        doc_id = conn.execute(
            """INSERT INTO documents (path, sha256, course, title, mime, status)
               VALUES (%s, %s, %s, %s, 'text/markdown', %s) RETURNING id""",
            (path, sha, course, path.rsplit("/", 1)[-1], status),
        ).fetchone()["id"]
        for i, t in enumerate(texts):
            conn.execute(
                "INSERT INTO chunks (document_id, ord, page, text, n_tokens, embedding) VALUES (%s, %s, 1, %s, %s, %s)",
                (doc_id, i, t, len(t.split()), fake_embed([t])[0]),
            )
    return doc_id


def doc(db, doc_id):
    with db.get_pool().connection() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()


def good_chat(messages, schema, temperature=0.3):
    return dict(GOOD)


def test_step_enriches_pending_documents_oldest_first(env):
    from app.enrich.worker import Enricher, counts

    _, db = env
    a = add_doc(db, "Course0/a.md")
    b = add_doc(db, "Course0/b.md")
    add_doc(db, "Course0/scan.pdf", status="empty_text", texts=())
    assert counts() == {"ok": 0, "error": 0, "pending": 2, "skipped": 1}

    e = Enricher(chat=good_chat, embed=fake_embed)
    assert e.step() is True
    assert doc(db, a)["summary"] == "Un résumé." and doc(db, a)["enrich_status"] == "ok"
    assert doc(db, a)["concepts"] == ["Gradient descent", "Loss"] and doc(db, a)["raw_tags"] == ["optimization", "stochastic gd"]
    assert doc(db, b)["summary"] is None
    assert e.step() is True and e.step() is False
    assert counts() == {"ok": 2, "error": 0, "pending": 0, "skipped": 1}


def test_changed_file_is_requeued_but_a_forced_reindex_of_the_same_file_is_not(env):
    from app.enrich.worker import Enricher, counts
    from app.ingest.pipeline import ingest_file

    inbox, _ = env
    f = inbox / "Course0" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("Le gradient est un vecteur de dérivées partielles.", encoding="utf-8")
    ingest_file(f, fake_embed, words)
    Enricher(chat=good_chat, embed=fake_embed).step()
    assert counts()["pending"] == 0

    ingest_file(f, fake_embed, words, force=True)
    assert counts()["pending"] == 0
    f.write_text("La hessienne est la matrice des dérivées secondes.", encoding="utf-8")
    ingest_file(f, fake_embed, words)
    assert counts()["pending"] == 1


def test_bad_output_is_an_error_and_the_file_stays_searchable(env):
    from app.enrich.worker import Enricher, counts

    _, db = env
    a = add_doc(db, "Course0/a.md")
    Enricher(chat=lambda m, s, temperature=0.3: {"summary": ""}, embed=fake_embed).step()
    d = doc(db, a)
    assert d["enrich_status"] == "error" and "missing a summary" in d["enrich_error"] and d["enriched_sha"] == "a"
    assert counts()["error"] == 1  # stored with the hash: not retried in a loop
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s", (a,)).fetchone()["n"] == 1


def test_a_file_that_changes_mid_summary_is_not_overwritten(env):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")

    def chat(messages, schema, temperature=0.3):
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE documents SET sha256 = 'b' WHERE id = %s", (a,))
        return dict(GOOD)

    Enricher(chat=chat, embed=fake_embed).step()
    d = doc(db, a)
    assert d["summary"] is None and d["enriched_sha"] is None  # still pending, for the new content


def test_no_llm_call_while_a_question_streams(env):
    from app.enrich.worker import Enricher
    from app.llm import busy

    _, db = env
    add_doc(db, "Course0/a.md")
    calls = []
    e = Enricher(chat=lambda m, s, temperature=0.3: calls.append(1) or dict(GOOD), embed=fake_embed, poll=0.01)
    with busy.answering():
        t = threading.Thread(target=e.step)
        t.start()
        time.sleep(0.2)
        assert calls == [] and e.status()["state"] == "waiting"
    t.join(2)
    assert calls == [1]


def test_pause_resume_and_rerun(env, tmp_path, monkeypatch):
    from app import config
    from app.enrich.worker import Enricher, counts

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    _, db = env
    a = add_doc(db, "Course0/a.md")
    add_doc(db, "Course1/b.md", course="Course1")
    e = Enricher(chat=good_chat, embed=fake_embed)
    e.pause()
    assert e.step() is False and e.status()["paused"] is True
    e.resume()
    assert e.step() and e.step()
    assert e.rerun(course="Course0") == 1 and counts()["pending"] == 1
    assert e.rerun(document_id=a) == 1
    config.get_settings.cache_clear()


def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import config
    from app.main import create_app

    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    config.get_settings.cache_clear()
    return TestClient(create_app())  # no `with`: no lifespan, so no background worker


def test_documents_carry_summary_fields(env, monkeypatch, tmp_path):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    b = add_doc(db, "Course0/b.md")
    Enricher(chat=good_chat, embed=fake_embed).step()
    rows = {r["id"]: r for r in client(monkeypatch, tmp_path).get("/documents").json()}
    assert rows[a]["summary"] == "Un résumé." and rows[a]["concepts"] == ["Gradient descent", "Loss"]
    assert (rows[a]["enrich_status"], rows[b]["enrich_status"]) == ("ok", "pending")


def test_enrich_admin_routes(env, monkeypatch, tmp_path):
    _, db = env
    add_doc(db, "Course0/a.md")
    c = client(monkeypatch, tmp_path)
    assert c.get("/admin/enrich").json()["counts"]["pending"] == 1
    assert c.post("/admin/enrich/pause").json()["paused"] is True
    assert c.post("/admin/enrich/resume").json()["paused"] is False
    assert c.post("/admin/enrich/rerun", json={}).status_code == 400
    assert c.post("/admin/enrich/rerun", json={"course": "Course0"}).json() == {"queued": 1}
    assert c.get("/admin/status").json()["enrichment"]["counts"]["pending"] == 1


def test_library_lists_files_that_could_not_be_summarised(env, monkeypatch, tmp_path):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    Enricher(chat=lambda m, s, temperature=0.3: {"summary": ""}, embed=fake_embed).step()
    errors = client(monkeypatch, tmp_path).get("/admin/library").json()["summary_errors"]
    assert [e["id"] for e in errors] == [a] and "missing a summary" in errors[0]["error"]


def axis_embed(groups):
    """Embedder where every string in the same group gets the same unit vector (cosine 1), others are orthogonal."""
    index = {s: i for i, g in enumerate(groups) for s in g}

    def embed(texts):
        out = []
        for t in texts:
            v = np.zeros(1024, dtype=np.float32)
            v[index.setdefault(t, len(index))] = 1.0  # an unknown string gets its own axis, stable within the test
            out.append(v)
        return out
    return embed


def tagged(db, path, raw_tags, course="Course0"):
    doc_id = add_doc(db, path, course=course)
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE documents SET raw_tags = %s, enriched_sha = sha256, enrich_status = 'ok' WHERE id = %s",
                     (Jsonb(raw_tags), doc_id))
    return doc_id


def names(course="Course0"):
    from app.enrich.vocab import list_tags

    return {t["name"]: t["count"] for t in list_tags(course, all_courses=False)}


EMBED = axis_embed([["kubernetes", "k8s", "container orchestration"], ["docker"], ["ci/cd", "continuous integration"]])


def test_vocabulary_merges_near_duplicates_under_the_most_frequent_form(env):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["kubernetes", "ci/cd"])
    tagged(db, "Course0/c.md", ["k8s", "continuous integration"])
    r = vocab.run("Course0", embed=EMBED)
    assert r["new_raw"] == 5 and r["new_tags"] == 3
    assert names() == {"kubernetes": 3, "docker": 1, "ci/cd": 2}
    assert sorted(t["name"] for t in vocab.document_tags(a)) == ["docker", "kubernetes"]
    assert vocab.run("Course0", embed=EMBED) == {"new_raw": 0, "new_tags": 0, "removed": 0}  # idempotent


def test_new_raw_tags_join_existing_tags_and_modules_stay_separate(env):
    from app.enrich import vocab

    _, db = env
    tagged(db, "Course0/a.md", ["kubernetes"])
    vocab.run("Course0", embed=EMBED)
    tagged(db, "Course0/b.md", ["container orchestration"])
    tagged(db, "Course1/c.md", ["kubernetes"], course="Course1")
    vocab.run("Course0", embed=EMBED)
    vocab.run("Course1", embed=EMBED)
    assert names() == {"kubernetes": 2}
    assert names("Course1") == {"kubernetes": 1}


def test_rename_merge_delete_survive_later_passes(env):
    from app.enrich import vocab

    _, db = env
    tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["ci/cd"])
    vocab.run("Course0", embed=EMBED)
    ids = {t["name"]: t["id"] for t in vocab.list_tags("Course0", all_courses=False)}

    assert vocab.rename(ids["kubernetes"], "  Kubernetes (K8s) ")["name"] == "kubernetes (k8s)"
    with pytest.raises(vocab.Clash):
        vocab.rename(ids["docker"], "kubernetes (k8s)")
    vocab.merge(ids["docker"], ids["kubernetes"])
    assert vocab.delete(ids["ci/cd"]) is True

    tagged(db, "Course0/c.md", ["docker", "ci/cd"])  # raw forms you merged away and deleted
    vocab.run("Course0", embed=EMBED)
    assert names() == {"kubernetes (k8s)": 2}


def test_unused_tags_are_removed_unless_you_named_them(env):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["docker"])
    b = tagged(db, "Course0/b.md", ["ci/cd"])
    vocab.run("Course0", embed=EMBED)
    vocab.rename(next(t["id"] for t in vocab.list_tags("Course0", all_courses=False) if t["name"] == "ci/cd"), "ci")
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = ANY(%s)", ([a, b],))
    assert vocab.run("Course0", embed=EMBED)["removed"] == 1
    assert names() == {"ci": 0}


def test_worker_links_known_tags_at_once_and_runs_the_pass_when_the_module_is_done(env):
    from app.enrich.worker import Enricher

    _, db = env
    add_doc(db, "Course0/a.md")
    add_doc(db, "Course0/b.md")
    e = Enricher(chat=good_chat, embed=EMBED)
    e.step()
    assert names() == {}  # b is still pending: no pass yet
    e.step()
    assert names() == {"optimization": 2, "stochastic gd": 2}


def test_tag_routes(env, monkeypatch, tmp_path):
    from app.enrich import vocab

    _, db = env
    a = tagged(db, "Course0/a.md", ["kubernetes", "docker"])
    tagged(db, "Course0/b.md", ["docker"])
    vocab.run("Course0", embed=EMBED)
    c = client(monkeypatch, tmp_path)

    tags = c.get("/tags", params={"course": "Course0"}).json()
    assert [(t["name"], t["count"]) for t in tags] == [("docker", 2), ("kubernetes", 1)]
    ids = {t["name"]: t["id"] for t in tags}
    doc_row = next(r for r in c.get("/documents").json() if r["id"] == a)
    assert [t["name"] for t in doc_row["tags"]] == ["docker", "kubernetes"]

    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": "Kubernetes"}).status_code == 409
    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": ""}).status_code == 422
    assert c.patch(f"/admin/tags/{ids['docker']}", json={"name": "Containers"}).json()["name"] == "containers"
    assert c.post("/admin/tags/merge", json={"from_id": ids["kubernetes"], "into": ids["docker"]}).status_code == 200
    assert [t["name"] for t in c.get("/tags", params={"course": "Course0"}).json()] == ["containers"]
    assert c.delete(f"/admin/tags/{ids['docker']}").status_code == 204
    assert c.delete(f"/admin/tags/{ids['docker']}").status_code == 404
    monkeypatch.setattr(vocab.ollama, "embed", EMBED)
    assert c.post("/admin/tags/vocab", json={"course": "Course0"}).json()["new_raw"] == 0


def unit(*pairs):
    v = np.zeros(1024, dtype=np.float32)
    for i, x in pairs:
        v[i] = x
    return v / np.linalg.norm(v)


def boost_fixture(db):
    """Chunk A is closer to the question (0.9 vs 0.85), but B's file summary matches the question and A's doesn't."""
    ids = []
    for path, chunk_vec, summary_vec in (("C/a.md", unit((0, 0.9), (1, 0.436)), unit((1, 1.0))),
                                         ("C/b.md", unit((0, 0.85), (2, 0.527)), unit((0, 1.0)))):
        with db.get_pool().connection() as conn:
            d = conn.execute(
                """INSERT INTO documents (path, sha256, course, title, mime, status, summary, summary_embedding)
                   VALUES (%s, 'x', 'C', %s, 'text/markdown', 'ok', 'About it. More.', %s) RETURNING id""",
                (path, path, summary_vec)).fetchone()["id"]
            conn.execute("INSERT INTO chunks (document_id, ord, page, text, n_tokens, embedding) VALUES (%s, 0, 1, 't', 1, %s)",
                         (d, chunk_vec))
        ids.append(d)
    return ids


def test_doc_boost_reorders_by_summary_and_refusal_uses_the_raw_score(env, monkeypatch):
    from app.config import get_settings
    from app.rag.retrieve import retrieve_with_vector

    _, db = env
    a, b = boost_fixture(db)
    q = unit((0, 1.0))
    hits, _ = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [h["doc_id"] for h in hits] == [a, b]  # doc_boost 0: today's order

    monkeypatch.setenv("DOC_BOOST", "0.1")
    get_settings.cache_clear()
    hits, _ = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [h["doc_id"] for h in hits] == [b, a]
    assert round(hits[0]["score"], 2) == 0.85  # the score shown and used for refusal is unchanged
    monkeypatch.setenv("MIN_SCORE", "0.88")
    get_settings.cache_clear()
    _, sources = retrieve_with_vector(q, "q", mode="dense", k=2)
    assert [s["doc_id"] for s in sources] == [a]
    get_settings.cache_clear()


def test_doc_context_adds_the_summary_line(monkeypatch):
    from app.config import get_settings
    from app.llm.prompts import first_sentence, format_context

    src = [{"title": "Chap 1", "page": 2, "mime": "application/pdf", "label": None, "text": "Body.",
            "summary": "Covers gradient descent. Also momentum."}]
    assert first_sentence("Covers gradient descent. Also momentum.") == "Covers gradient descent."
    assert "About this file" not in format_context(src)
    monkeypatch.setenv("DOC_CONTEXT", "on")
    get_settings.cache_clear()
    assert "[1] (Chap 1, p. 2)\nAbout this file: Covers gradient descent.\nBody." in format_context(src)
    get_settings.cache_clear()


def test_worker_embeds_summaries_and_backfills_missing_ones(env):
    from app.enrich.worker import Enricher

    _, db = env
    a = add_doc(db, "Course0/a.md")
    e = Enricher(chat=good_chat, embed=fake_embed)
    e.step()
    assert doc(db, a)["summary_embedding"] is not None
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE documents SET summary_embedding = NULL")
    assert e.step() is True  # nothing pending: embeds the summary that lacks a vector
    assert doc(db, a)["summary_embedding"] is not None and e.step() is False


def test_idle_worker_runs_a_missed_vocabulary_pass(env):
    from app.enrich.worker import Enricher

    _, db = env
    tagged(db, "Course0/a.md", ["kubernetes", "docker"])  # summarised, but no pass ever ran for the module
    tagged(db, "Course1/b.md", ["docker"], course="Course1")
    e = Enricher(chat=good_chat, embed=EMBED)
    assert e.step() is True
    assert e.step() is True  # one module per step
    assert names() == {"kubernetes": 1, "docker": 1} and names("Course1") == {"docker": 1}
    assert e.step() is False  # every raw tag has an alias now
