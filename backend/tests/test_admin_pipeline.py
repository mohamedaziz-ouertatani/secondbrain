import pytest
from fakes import fake_embed, words


def note(inbox, rel, body="Paragraph about gaussian vectors and their characteristic function. " * 20):
    p = inbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def paths(db):
    with db.get_pool().connection() as conn:
        return sorted(r["path"] for r in conn.execute("SELECT path FROM documents"))


def test_exclude_include_and_rescan(env):
    from app.ingest.pipeline import exclude, include, ingest_file, rescan

    inbox, db = env
    a = note(inbox, "Prob/a.md")
    note(inbox, "Prob/b.md")
    assert rescan(fake_embed, words)["ok"] == 2

    assert exclude("Prob/a.md") is True
    assert paths(db) == ["Prob/b.md"]
    assert exclude("Prob/a.md") is False  # idempotent, nothing left to remove
    assert ingest_file(a, fake_embed, words) == "excluded"
    stats = rescan(fake_embed, words)
    assert stats["excluded"] == 1 and stats["removed"] == 0
    assert paths(db) == ["Prob/b.md"]

    assert include("Prob/a.md", fake_embed, words) == "ok"
    assert paths(db) == ["Prob/a.md", "Prob/b.md"]
    assert include("Prob/a.md", fake_embed, words) is None  # no longer excluded


def test_rescan_drops_stale_row_of_excluded_file(env):
    from app.ingest.pipeline import rescan

    inbox, db = env
    note(inbox, "Prob/a.md")
    rescan(fake_embed, words)
    with db.get_pool().connection() as conn:  # excluded behind the pipeline's back
        conn.execute("INSERT INTO excluded_paths (path) VALUES ('Prob/a.md')")
    assert rescan(fake_embed, words)["removed"] == 1
    assert paths(db) == []


@pytest.mark.usefixtures("env")
def test_include_missing_file():
    from app.ingest.pipeline import exclude, include

    exclude("Gone/x.md")
    assert include("Gone/x.md", fake_embed, words) == "missing"


def test_forced_reindex_of_unchanged_file_and_course(env):
    from app.ingest.pipeline import ingest_file, reindex

    inbox, _ = env
    a = note(inbox, "Prob/a.md")
    note(inbox, "Prob/b.md")
    note(inbox, "Algo/c.md")
    for p in inbox.rglob("*.md"):
        ingest_file(p, fake_embed, words)
    assert ingest_file(a, fake_embed, words) == "skipped"
    assert ingest_file(a, fake_embed, words, force=True) == "ok"

    calls = []

    def counting_embed(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    assert reindex(course="Prob", embedder=counting_embed, counter=words) == {"ok": 2}
    assert len(calls) == 2  # Algo untouched
    assert reindex(rel="Algo/c.md", embedder=fake_embed, counter=words) == {"ok": 1}


def test_remove_folder_only_drops_that_prefix(env):
    from app.ingest.pipeline import remove_folder, rescan

    inbox, db = env
    note(inbox, "Prob/a.md")
    note(inbox, "Prob/sub/b.md")
    note(inbox, "Prob 2/c.md")  # shares the "Prob" prefix but is another folder
    rescan(fake_embed, words)
    assert remove_folder(inbox / "Prob") == 2
    assert paths(db) == ["Prob 2/c.md"]
