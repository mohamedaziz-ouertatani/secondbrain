"""Shared fixtures. `env` runs against a throwaway Postgres DB (docker compose); skipped if unreachable."""

import os

import psycopg
import pytest

BASE_URL = os.environ.get("TEST_DATABASE_URL_ADMIN", "postgresql://secondbrain:secondbrain@localhost:5433/secondbrain")
TEST_DB = "secondbrain_test"


@pytest.fixture
def env(tmp_path, monkeypatch):
    try:
        with psycopg.connect(BASE_URL, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.OperationalError:
        pytest.skip("postgres not reachable")
    url = BASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))

    from app import db
    from app.config import get_settings

    get_settings.cache_clear()
    db.close_pool()
    db.migrate()
    yield tmp_path, db
    db.close_pool()
    get_settings.cache_clear()
