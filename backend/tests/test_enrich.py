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

    monkeypatch.setattr(answer, "retrieve", lambda q, c: ([], []))  # refused: no LLM call
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

    inbox, db = env
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
