"""Blackboard sync logic against a fake API shaped like esprit.blackboard.com's real responses."""

import pytest

from app.sync import blackboard as bb
from app.sync.blackboard import API, clean_course_name, match_folder, safe_segment

C = "_28278_1"
FIELDS = bb.CONTENT_FIELDS


def file_item(id_, name, modified="2026-09-25T10:00:00Z"):
    return {"id": id_, "title": name, "modified": modified, "availability": {"available": "Yes"},
            "contentHandler": {"id": "resource/x-bb-file", "file": {"fileName": name}}}


def folder(id_, title, handler="resource/x-bb-folder"):
    return {"id": id_, "title": title, "hasChildren": True, "modified": "2026-09-25T10:00:00Z",
            "availability": {"available": "Yes"}, "contentHandler": {"id": handler}}


class FakeAPI:
    def __init__(self, files_modified="2026-09-25T10:00:00Z"):
        m = files_modified
        self.routes = {
            f"{API}/users/me?fields=id": {"id": "_1_1"},
            f"{API}/courses/{C}/contents?{FIELDS}": {"results": [
                folder("L1", "Chapter 1 : Gaussian vectors", "resource/x-bb-lesson"),
                {"id": "X", "title": "Zoom link", "contentHandler": {"id": "resource/x-bb-externallink"}},
                {**folder("H", "Hidden"), "availability": {"available": "No"}},
            ]},
            f"{API}/courses/{C}/contents/L1/children?{FIELDS}": {
                "results": [folder("F1", "Document Chap1")],
                "paging": {"nextPage": f"{API}/courses/{C}/contents/L1/children?page2"},
            },
            f"{API}/courses/{C}/contents/L1/children?page2": {"results": [
                file_item("V", "lecture.mp4"),  # unreadable: skipped without an attachments call
                {"id": "D", "title": "Exercises", "modified": m, "contentHandler": {"id": "resource/x-bb-document"}},
            ]},
            f"{API}/courses/{C}/contents/F1/children?{FIELDS}": {"results": [
                file_item("P1", "CHAP1.pdf", m), file_item("P2", "Serie 1.pdf", m)]},
            f"{API}/courses/{C}/contents/P1/attachments": {"results": [{"id": "A1", "fileName": "CHAP1.pdf"}]},
            f"{API}/courses/{C}/contents/P2/attachments": {"results": [{"id": "A2", "fileName": "Serie 1.pdf"}]},
            f"{API}/courses/{C}/contents/D/attachments": {"results": [
                {"id": "A3", "fileName": "td1.docx"}, {"id": "A4", "fileName": "data.csv"}]},
        }
        self.calls: list[str] = []
        self.errors: dict[str, int] = {}

    def get(self, path):
        self.calls.append(path)
        if path in self.errors:
            raise bb.APIError(path, self.errors[path])
        return self.routes[path]

    def download(self, path):
        return f"bytes of {path.split('/')[-2]}".encode()


def test_clean_course_name_and_matching():
    folders = ["Probability 2", "DEVOPS", "Big Data Analytics", "Optimization for ML"]
    assert clean_course_name("Probability 2__5DS1") == "Probability 2"
    assert match_folder({"id": "_1", "name": "DEVOPS__5DS1"}, folders, {}) == "DEVOPS"
    assert match_folder({"id": "_1", "name": "Big data analytics__5DS1"}, folders, {}) == "Big Data Analytics"
    assert match_folder({"id": "_1", "name": "Engineering Internship__5DS1"}, folders, {}) is None
    assert match_folder({"id": "_9", "name": "Credit-1"}, folders, {"_9": "DEVOPS"}) == "DEVOPS"


def test_safe_segment_windows():
    assert safe_segment("Chapter 1 : Gaussian vectors") == "Chapter 1 - Gaussian vectors"
    assert safe_segment('a/b\\c?"*.. ') == "a-b-c---"
    assert safe_segment("...") == "untitled"


def test_walk_finds_readable_files_in_nested_folders():
    api = FakeAPI()
    files = list(bb.walk(api, C))
    assert [(f.folders, f.file_name) for f in files] == [
        (["Chapter 1 : Gaussian vectors", "Document Chap1"], "CHAP1.pdf"),
        (["Chapter 1 : Gaussian vectors", "Document Chap1"], "Serie 1.pdf"),
        (["Chapter 1 : Gaussian vectors"], "td1.docx"),
    ]
    assert not any("/V/" in c or "/X/" in c or "/H/" in c for c in api.calls)


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "inbox"))
    monkeypatch.setattr(bb, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(bb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bb, "my_courses", lambda api: [{"id": C, "name": "Probability 2__5DS1"},
                                                        {"id": "_2", "name": "Engineering Internship__5DS1"}])
    from app.config import get_settings

    get_settings.cache_clear()
    root = tmp_path / "inbox"
    (root / "Probability 2").mkdir(parents=True)
    yield root
    get_settings.cache_clear()


def sync(api, **kw):
    return bb.run(api, probe=False, dry_run=False, only=None, include_unmapped=False, **kw)


def test_sync_downloads_then_skips_then_updates(inbox, capsys):
    target = inbox / "Probability 2" / "Chapter 1 - Gaussian vectors" / "Document Chap1" / "CHAP1.pdf"

    sync(FakeAPI())
    assert target.read_bytes() == b"bytes of A1"
    assert (inbox / "Probability 2" / "Chapter 1 - Gaussian vectors" / "td1.docx").exists()
    assert not list(inbox.rglob("*.part"))
    assert not (inbox / "Engineering Internship").exists()  # unmapped course skipped

    capsys.readouterr()
    sync(FakeAPI())
    assert "0 to download, 3 unchanged" in capsys.readouterr().out

    target.unlink()  # deleted locally: left alone
    sync(FakeAPI())
    assert not target.exists()

    sync(FakeAPI(files_modified="2026-10-01T00:00:00Z"))  # changed on Blackboard: fetched again
    assert target.exists()


def test_existing_identical_file_is_adopted(inbox, capsys):
    d = inbox / "Probability 2" / "Chapter 1 - Gaussian vectors" / "Document Chap1"
    d.mkdir(parents=True)
    (d / "CHAP1.pdf").write_bytes(b"bytes of A1")  # same content, added by hand
    (d / "Serie 1.pdf").write_bytes(b"my own edited copy")
    sync(FakeAPI())
    out = capsys.readouterr().out
    assert "already had     Probability 2/Chapter 1 - Gaussian vectors/Document Chap1/CHAP1.pdf" in out
    assert (d / "Serie 1.pdf").read_bytes() == b"my own edited copy"  # never overwritten
    assert (d / "Serie 1 (P2).pdf").read_bytes() == b"bytes of A2"
    assert not (d / "CHAP1 (P1).pdf").exists()


def test_dry_run_and_probe_download_nothing(inbox):
    bb.run(FakeAPI(), probe=True, dry_run=False, only=None, include_unmapped=False)
    bb.run(FakeAPI(), probe=False, dry_run=True, only=None, include_unmapped=False)
    assert not [p for p in inbox.rglob("*") if p.is_file()]


def test_items_refusing_attachments_are_skipped():
    api = FakeAPI()
    api.errors[f"{API}/courses/{C}/contents/D/attachments"] = 400  # Ultra document body
    api.errors[f"{API}/courses/{C}/contents/F1/children?{FIELDS}"] = 403  # release conditions
    assert list(bb.walk(api, C)) == []

    api = FakeAPI()
    api.errors[f"{API}/courses/{C}/contents?{FIELDS}"] = 500  # real failures still surface
    with pytest.raises(bb.APIError):
        list(bb.walk(api, C))


def test_ultra_page_becomes_note_and_embedded_pdf_is_fetched(inbox, monkeypatch):
    api = FakeAPI()
    meta = '{&quot;linkName&quot;: &quot;S1.pdf&quot;}'
    body = ("<p>" + "Exercices sur les vecteurs gaussiens et le mouvement brownien. " * 2 + "</p>"
            f'<a href="https://esprit.blackboard.com/bbcswebdav/xid-77_1?s=1" data-bbfile="{meta}">S1.pdf</a>'
            f'<a href="https://evil.example.com/x.pdf" data-bbfile="{meta}">x</a>')
    api.routes[f"{API}/courses/{C}/contents?{FIELDS}"]["results"].append(folder("DOC", "Serie 1", "resource/x-bb-document"))
    api.routes[f"{API}/courses/{C}/contents/DOC/children?{FIELDS}"] = {"results": [
        {"id": "B", "title": "ultraDocumentBody", "modified": "m", "body": body,
         "contentHandler": {"id": "resource/x-bb-document"}}]}
    downloaded = []
    api.download = lambda url: downloaded.append(url) or b"pdf"
    sync(api)
    note = inbox / "Probability 2" / "Serie 1.md"
    assert note.read_text(encoding="utf-8").startswith("# Serie 1\n\n*Probability 2*\n")
    assert (inbox / "Probability 2" / "Serie 1" / "S1.pdf").read_bytes() == b"pdf"
    assert not any("evil" in u for u in downloaded)
    assert f"{API}/courses/{C}/contents/B/attachments" not in api.calls  # bodies have no attachments


def test_replace_retries_transient_lock(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("x")
    real, fails = bb.os.replace, iter([True, True, False])

    def flaky(a, b):
        if next(fails):
            raise PermissionError("locked")
        real(a, b)

    monkeypatch.setattr(bb.os, "replace", flaky)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    bb.replace_with_retry(src, dst)
    assert dst.read_text() == "x"


def test_run_emits_events_for_each_mode(inbox):
    ev = []
    bb.run(FakeAPI(), probe=True, dry_run=False, only=None, include_unmapped=False, emit=ev.append)
    assert [e["type"] for e in ev] == ["courses", "done"]
    assert ev[0]["probe"] is True and ev[1]["mode"] == "probe"
    assert any(c["folder"] == "Probability 2" for c in ev[0]["courses"])
    assert any(c["folder"] is None for c in ev[0]["courses"])  # an unmapped course is listed as skipped

    ev.clear()
    bb.run(FakeAPI(), probe=False, dry_run=True, only=None, include_unmapped=False, emit=ev.append)
    files = [e for e in ev if e["type"] == "file"]
    assert {e["action"] for e in files} == {"would_download"} and len(files) == 3
    assert next(e for e in ev if e["type"] == "course")["to_download"] == 3
    assert ev[-1] == {"type": "done", "mode": "preview", "files": 0, "bytes": 0}

    ev.clear()
    bb.run(FakeAPI(), probe=False, dry_run=False, only=None, include_unmapped=False, emit=ev.append)
    files = [e for e in ev if e["type"] == "file"]
    assert [e["action"] for e in files] == ["downloaded"] * 3 and all(e["kb"] >= 1 for e in files)
    assert ev[-1]["type"] == "done" and ev[-1]["mode"] == "sync" and ev[-1]["files"] == 3


def test_json_event_is_one_line_per_event(capsys):
    bb.json_event({"type": "file", "path": "Probabilité/é.pdf"})
    assert capsys.readouterr().out == '{"type": "file", "path": "Probabilité/é.pdf"}\n'


def test_headless_expired_session_exits_3(monkeypatch, capsys):
    class ExpiredAPI:
        def __init__(self, headless=False):
            self.headless = headless

        def ensure_login(self, headless=False, timeout_s=600, emit=None):
            raise bb.LoginRequired

        def close(self):
            pass

    monkeypatch.setattr(bb, "PlaywrightAPI", ExpiredAPI)
    assert bb.main(["--headless", "--json"]) == 3
    assert capsys.readouterr().out.strip() == '{"type": "login_required"}'


def test_deadlines_step_reports_and_never_fails_the_sync(inbox, monkeypatch):
    from app.planner import blackboard as pb

    seen = {}

    def fake(api, folders, dry_run=False):
        seen.update(folders=folders, dry_run=dry_run)
        return {"type": "deadlines", "new": 1, "updated": 0, "removed": 0}

    monkeypatch.setattr(pb, "import_deadlines", fake)
    ev = []
    assert sync(FakeAPI(), emit=ev.append) == 0
    assert seen == {"folders": {C: "Probability 2"}, "dry_run": False}  # unmapped courses left out
    assert [e for e in ev if e["type"] == "deadlines"] == [{"type": "deadlines", "new": 1, "updated": 0, "removed": 0}]
    assert ev[-1]["type"] == "done"

    def boom(api, folders, dry_run=False):
        raise RuntimeError("calendar 500")

    monkeypatch.setattr(pb, "import_deadlines", boom)
    ev.clear()
    assert sync(FakeAPI(), emit=ev.append) == 0
    assert {"type": "deadlines", "failed": "calendar 500"} in ev

    ev.clear()
    bb.run(FakeAPI(), probe=True, dry_run=False, only=None, include_unmapped=False, emit=ev.append)
    assert not [e for e in ev if e["type"] == "deadlines"]


def test_deadlines_follow_the_course_filter(inbox, monkeypatch):
    from app.planner import blackboard as pb

    seen = {}
    monkeypatch.setattr(pb, "import_deadlines",
                        lambda api, folders, dry_run=False: seen.update(folders=folders) or {"type": "deadlines"})
    bb.run(FakeAPI(), probe=False, dry_run=True, only="devops", include_unmapped=False, emit=lambda e: None)
    assert seen["folders"] == {}
