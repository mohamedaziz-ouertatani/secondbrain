import pymupdf
import pytest
from fakes import fake_embed, words


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())  # no `with`: no watcher


@pytest.fixture
def parse_calls(monkeypatch):
    """Counts parses done for the reader (ingest has already run when the test starts counting)."""
    from app.ingest import pipeline

    calls = []
    real = pipeline.parse

    def counting(path):
        calls.append(path.name)
        return real(path)

    monkeypatch.setattr(pipeline, "parse", counting)
    return calls


def _library(inbox):
    (inbox / "Optim").mkdir(parents=True)
    with pymupdf.open() as pdf:
        for n in (1, 2):
            pdf.new_page().insert_text((72, 72), f"Page {n}: the norm of u is the square root of the sum of squares.")
        pdf.save(inbox / "Optim" / "norms.pdf")
    (inbox / "Optim" / "note.md").write_text("# Norms\n\nA note about the triangle inequality. " * 3, encoding="utf-8")


def test_reader_pages_come_from_ingest_without_reparsing(env, client, monkeypatch):
    from app.ingest import pipeline
    from app.ingest.pipeline import rescan

    inbox, _ = env
    _library(inbox)
    rescan(fake_embed, words)
    ids = {d["path"]: d["id"] for d in client.get("/documents").json()}

    def boom(path):
        raise AssertionError(f"reader re-parsed {path.name}")

    monkeypatch.setattr(pipeline, "parse", boom)
    body = client.get(f"/documents/{ids['Optim/norms.pdf']}/pages").json()
    assert body["path"] == "Optim/norms.pdf" and body["page_count"] == 2
    assert [p["page"] for p in body["pages"]] == [1, 2]
    assert all(p["label"] is None for p in body["pages"])
    assert body["pages"][1]["text"].startswith("Page 2: the norm of u")
    assert "tags" in body


def test_reader_parses_once_when_not_stored(env, client, parse_calls):
    from app.ingest.pipeline import rescan
    from app.ingest.parse import parse

    inbox, db = env
    _library(inbox)
    rescan(fake_embed, words)
    ids = {d["path"]: d["id"] for d in client.get("/documents").json()}
    with db.get_pool().connection() as conn:  # as for files ingested before pages were kept
        conn.execute("DELETE FROM page_texts")
    parse_calls.clear()

    url = f"/documents/{ids['Optim/norms.pdf']}/pages"
    first = client.get(url).json()
    second = client.get(url).json()
    assert parse_calls == ["norms.pdf"]
    assert first == second
    expected = parse(inbox / "Optim" / "norms.pdf").pages
    assert [p["text"] for p in first["pages"]] == expected


def test_reader_follows_file_edits_and_old_versions_are_pruned(env, client, parse_calls):
    from app.ingest.pipeline import rescan

    inbox, db = env
    _library(inbox)
    rescan(fake_embed, words)
    ids = {d["path"]: d["id"] for d in client.get("/documents").json()}
    note = inbox / "Optim" / "note.md"
    url = f"/documents/{ids['Optim/note.md']}/pages"
    parse_calls.clear()

    note.write_text("# Norms\n\nEdited: the Cauchy-Schwarz inequality.", encoding="utf-8")
    assert "Cauchy-Schwarz" in client.get(url).json()["pages"][0]["text"]  # not re-ingested yet
    assert parse_calls == ["note.md"]

    rescan(fake_embed, words)  # re-ingests the edit; the pre-edit pages go
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM page_texts").fetchone()["n"] == 2

    from app.ingest.pipeline import remove_file

    remove_file(note)
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM page_texts").fetchone()["n"] == 1
