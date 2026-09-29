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
