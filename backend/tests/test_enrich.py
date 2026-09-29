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
