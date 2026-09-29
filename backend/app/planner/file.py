"""File a note into inbox/<module>/ as Markdown, where the watcher indexes it and answers can cite it."""

from ..config import get_settings
from ..sync.blackboard import safe_segment, write_atomic
from . import store


def render(item: dict) -> bytes:
    return f"# {item['title'].strip() or 'Note'}\n\n{item['body'].strip()}\n".encode("utf-8")


def file_note(item: dict) -> str:
    """Write a new .md for the note, never over an existing file. Returns its inbox-relative path."""
    inbox = get_settings().inbox
    folder = inbox / safe_segment(item["course"])
    name = safe_segment(item["title"] or "Note")
    target, n = folder / f"{name}.md", 2
    while target.exists():
        target, n = folder / f"{name} ({n}).md", n + 1
    write_atomic(target, render(item))
    return target.relative_to(inbox).as_posix()


def rewrite(item: dict) -> None:
    write_atomic(get_settings().inbox / item["filed_path"], render(item))


def reconcile(item: dict) -> dict:
    """A filed note whose file is gone from disk is no longer filed; it keeps its last text."""
    if item["filed_path"] and not (get_settings().inbox / item["filed_path"]).is_file():
        return store.set_filed(item["id"], None) or item
    return item
