from fakes import fake_embed, words
from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileDeletedEvent,
)


def drain(w):
    for path, retries in w._due():
        w._process(path, retries)


def paths(db):
    with db.get_pool().connection() as conn:
        return sorted(r["path"] for r in conn.execute("SELECT path FROM documents"))


def test_folder_delete_rename_and_paste(env, monkeypatch):
    from app.ingest import pipeline, watcher
    from app.ingest.pipeline import rescan

    inbox, db = env
    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    monkeypatch.setattr(watcher, "DEBOUNCE_S", 0)
    for rel in ("Old/a.md", "Old/sub/b.md", "Keep/c.md"):
        p = inbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("Some text about brownian motion increments. " * 10, encoding="utf-8")
    rescan(fake_embed, words)

    w = watcher.InboxWatcher()  # not started: no real filesystem watching
    handler = watcher._Handler(w)

    # rename Old -> New: old paths leave, files are re-ingested under the new module
    (inbox / "Old").rename(inbox / "New")
    handler.on_any_event(DirMovedEvent(str(inbox / "Old"), str(inbox / "New")))
    drain(w)
    assert paths(db) == ["Keep/c.md", "New/a.md", "New/sub/b.md"]

    # delete a whole module folder
    for f in sorted((inbox / "New").rglob("*"), reverse=True):
        if f.is_file():
            f.unlink()
        else:
            f.rmdir()
    (inbox / "New").rmdir()
    handler.on_any_event(DirDeletedEvent(str(inbox / "New")))
    assert paths(db) == ["Keep/c.md"]

    # Windows can't stat a deleted path, so a deleted folder arrives as a *file* delete event
    (inbox / "Gone").mkdir()
    (inbox / "Gone" / "e.md").write_text("A note that will vanish with its folder. " * 10, encoding="utf-8")
    rescan(fake_embed, words)
    (inbox / "Gone" / "e.md").unlink()
    (inbox / "Gone").rmdir()
    handler.on_any_event(FileDeletedEvent(str(inbox / "Gone")))
    assert paths(db) == ["Keep/c.md"]

    # a folder pasted in one go
    (inbox / "Pasted").mkdir()
    (inbox / "Pasted" / "d.md").write_text("Pasted note about stochastic processes. " * 10, encoding="utf-8")
    handler.on_any_event(DirCreatedEvent(str(inbox / "Pasted")))
    drain(w)
    assert paths(db) == ["Keep/c.md", "Pasted/d.md"]
