"""Sync course files from Blackboard Learn (Ultra) into inbox/<module>/.

You log in yourself in a real browser window (Edge by default); the session is kept in
backend/data/bb-profile so later runs usually skip the login. Files are fetched through
Blackboard's REST API with that session, only for readable types, and only when new or
changed. Nothing local is ever deleted.

    uv run python -m app.sync.blackboard --probe      # log in, show course mapping, download nothing
    uv run python -m app.sync.blackboard --dry-run    # list what would be downloaded
    uv run python -m app.sync.blackboard              # sync
"""

import argparse
import difflib
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from ..config import ROOT, get_settings
from ..ingest.parse import SUPPORTED
from ..planner import blackboard as planner_bb
from . import ultra_pages

log = logging.getLogger("blackboard")

API = "/learn/api/public/v1"
DATA_DIR = ROOT / "backend" / "data"
STATE_FILE = DATA_DIR / "blackboard-sync.json"
PROFILE_DIR = DATA_DIR / "bb-profile"
# Blackboard's login cookie is a session cookie, which the browser drops on close; keep a copy.
COOKIES_FILE = DATA_DIR / "bb-cookies.json"

CONTAINER_HANDLERS = {"resource/x-bb-folder", "resource/x-bb-lesson"}
# Item types that can carry file attachments. Links, tests, LTI tools etc. never do.
FILE_HANDLERS = {"resource/x-bb-file", "resource/x-bb-document", "resource/x-bb-assignment"}


class APIError(RuntimeError):
    def __init__(self, path: str, status: int):
        super().__init__(f"GET {path} -> {status}")
        self.status = status


# Item-level refusals: Ultra document bodies don't support attachments (400), content hidden by
# release conditions (403), items removed mid-walk (404). Skip those, fail on anything else.
SKIPPABLE = {400, 403, 404}


class BlackboardAPI(Protocol):
    def get(self, path: str) -> dict: ...
    def download(self, path: str) -> bytes: ...


# --- course → inbox folder ------------------------------------------------


def clean_course_name(name: str) -> str:
    """'Probability 2__5DS1' -> 'Probability 2' (drops the class-group suffix)."""
    return re.sub(r"__[A-Za-z0-9]+$", "", name).strip()


def match_folder(course: dict, folders: list[str], overrides: dict[str, str]) -> str | None:
    """Pick the inbox folder for a course: override by name/id, then exact, then close match."""
    name = clean_course_name(course["name"])
    for key in (course["name"], name, course["id"], course.get("courseId", "")):
        if key in overrides:
            return overrides[key]
    by_fold = {f.casefold(): f for f in folders}
    if name.casefold() in by_fold:
        return by_fold[name.casefold()]
    close = difflib.get_close_matches(name.casefold(), list(by_fold), n=1, cutoff=0.85)
    return by_fold[close[0]] if close else None


# --- walking course content ----------------------------------------------

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_segment(s: str, limit: int = 80) -> str:
    """A title usable as one Windows path segment."""
    s = _BAD_CHARS.sub("-", s).strip().rstrip(". ")
    return (s[:limit].rstrip(". ") or "untitled")


@dataclass
class RemoteFile:
    course_id: str
    content_id: str
    attachment_id: str
    folders: list[str]  # content titles from the course root down
    file_name: str
    modified: str
    url: str | None = None  # file embedded in an Ultra page: fetched from its own URL
    text: str | None = None  # Ultra page text, already converted to Markdown

    @property
    def key(self) -> str:
        return f"{self.course_id}/{self.content_id}/{self.attachment_id}"


def readable(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in SUPPORTED


def paged(api: BlackboardAPI, path: str, skippable: bool = False) -> Iterator[dict]:
    while path:
        try:
            page = api.get(path)
        except APIError as e:
            if skippable and e.status in SKIPPABLE:
                log.debug("skipped %s", e)
                return
            raise
        yield from page.get("results", [])
        path = page.get("paging", {}).get("nextPage")


CONTENT_FIELDS = "fields=id,title,contentHandler,hasChildren,modified,availability.available,body"

# Ultra stores a document's text in a child item with this title; the document is its parent.
ULTRA_BODY = "ultraDocumentBody"


def walk(api: BlackboardAPI, course_id: str, skipped: Counter | None = None, course_name: str = "") -> Iterator[RemoteFile]:
    """Yield readable files; count unreadable ones by extension into `skipped`."""
    skipped = skipped if skipped is not None else Counter()

    def skip(name: str) -> None:
        skipped[Path(name).suffix.lower() or "(no extension)"] += 1

    def page(item: dict, folders: list[str]) -> Iterator[RemoteFile]:
        """A page's text as <title>.md, and its embedded files in a <title>/ folder beside it."""
        if item["title"] == ULTRA_BODY and folders:
            title, parent = folders[-1], folders[:-1]
        else:
            title, parent = item["title"], folders
        # Teachers reuse titles like "Summary..." per section, so name notes with their section too.
        clean = title.strip().rstrip(".…").strip() or title
        heading = f"{clean} — {parent[-1]}" if parent else clean
        assets = safe_segment(title)  # where plan_course saves the embedded files
        note, embedded = ultra_pages.convert(item["body"], heading, breadcrumb=[p for p in (course_name, *parent) if p],
                                             image_path=lambda name: f"{assets}/{safe_segment(name, 120)}")
        modified = item.get("modified", "")
        if note:
            yield RemoteFile(course_id, item["id"], "page", parent, f"{safe_segment(clean)}.md", modified, text=note)
        host = urlsplit(get_settings().blackboard_url).netloc
        for e in embedded:
            if urlsplit(e.url).netloc != host:  # only files hosted on Blackboard itself
                continue
            if readable(e.name) or ultra_pages.is_image(e.name):  # images: shown in the note
                yield RemoteFile(course_id, item["id"], e.key, parent + [title], e.name, modified, url=e.url)
            else:
                skip(e.name)

    def visit(path: str, folders: list[str], skippable: bool = False) -> Iterator[RemoteFile]:
        for item in paged(api, path, skippable):
            if (item.get("availability") or {}).get("available") == "No":
                continue
            handler = item.get("contentHandler") or {}
            hid = handler.get("id", "")
            if item.get("body"):
                yield from page(item, folders)
            if item.get("hasChildren") or hid in CONTAINER_HANDLERS:
                yield from visit(
                    f"{API}/courses/{course_id}/contents/{item['id']}/children?{CONTENT_FIELDS}",
                    folders + [item["title"]],
                    skippable=True,
                )
                continue
            if hid not in FILE_HANDLERS or item["title"] == ULTRA_BODY:  # a body has no attachments
                continue
            # x-bb-file names its file up front: skip unreadable types without a request.
            known = (handler.get("file") or {}).get("fileName")
            if known and not readable(known):
                skip(known)
                continue
            for att in paged(api, f"{API}/courses/{course_id}/contents/{item['id']}/attachments", skippable=True):
                if not readable(att["fileName"]):
                    skip(att["fileName"])
                else:
                    yield RemoteFile(course_id, item["id"], att["id"], folders, att["fileName"],
                                     item.get("modified", ""))

    yield from visit(f"{API}/courses/{course_id}/contents?{CONTENT_FIELDS}", [])


# --- planning and syncing -------------------------------------------------


@dataclass
class Plan:
    # (file, target, adopt): adopt=True means a file you added yourself already sits at target;
    # it is kept if identical, otherwise the download is saved next to it.
    download: list[tuple[RemoteFile, Path, bool]] = field(default_factory=list)
    unchanged: int = 0
    deleted_locally: int = 0


def plan_course(files: list[RemoteFile], module_dir: Path, state: dict, inbox: Path) -> Plan:
    plan = Plan()
    claimed: set[Path] = {inbox / v["path"] for v in state.values()}
    for f in files:
        prev = state.get(f.key)
        if prev:
            target = inbox / prev["path"]
            if prev.get("modified") == f.modified:
                if not target.exists():
                    plan.deleted_locally += 1  # you removed it; respect that
                    continue
                # A page note is rebuilt every run: keep it unless the conversion itself changed.
                if f.text is None or target.read_bytes() == f.text.encode("utf-8"):
                    plan.unchanged += 1
                    continue
            plan.download.append((f, target, False))  # changed on Blackboard: overwrite in place
            continue
        target = module_dir.joinpath(*(safe_segment(s) for s in f.folders), safe_segment(f.file_name, 120))
        if target in claimed:  # two Blackboard items with the same name in one folder
            target = with_id(target, f)
        claimed.add(target)
        plan.download.append((f, target, target.exists()))
    return plan


def with_id(target: Path, f: RemoteFile) -> Path:
    return target.with_name(f"{target.stem} ({f.content_id}){target.suffix}")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def replace_with_retry(src: Path, dst: Path, attempts: int = 10) -> None:
    """os.replace, retried: on Windows, antivirus or the search indexer briefly locks fresh files."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.2 * (i + 1))


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    replace_with_retry(tmp, STATE_FILE)


def write_atomic(target: Path, data: bytes) -> None:
    """Write via a .part file (ignored by the inbox watcher) so it never ingests half a file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    part.write_bytes(data)
    replace_with_retry(part, target)


# --- events: what a run reports, printed as today's text or as JSON lines (--json) --------------

# 15-character labels keep the text output byte-for-byte what it was before events existed
LABEL = {
    "would_download": "would download ", "would_save_page": "would save page", "failed": "FAILED         ",
    "already_had": "already had    ", "downloaded": "downloaded     ", "saved_page": "saved page     ",
}


class LoginRequired(RuntimeError):
    """Headless run with an expired Blackboard session."""


def print_event(e: dict) -> None:
    t = e["type"]
    if t == "courses":
        print(f"\n{len(e['courses'])} courses on Blackboard:")
        for c in e["courses"]:
            print(f"  {'->' if c['folder'] else '  '} {c['name']:<45} {c['folder'] or '(skipped: no inbox folder)'}")
        if e["probe"]:
            print("\nProbe only: nothing downloaded. Fix wrong matches with blackboard_course_map in config.yaml.")
    elif t == "course":
        print(f"\n{e['folder']}: {e['files']} readable files, {e['to_download']} to download, {e['unchanged']} unchanged"
              + (f", {e['deleted_locally']} deleted locally (left alone)" if e["deleted_locally"] else ""))
        if e["skipped"]:
            print("  skipped, not readable yet: " + ", ".join(f"{n} {ext}" for ext, n in e["skipped"].items()))
    elif t == "file":
        a = e["action"]
        tail = (f": {e['error']}" if a == "failed"
                else f" ({e['kb']} KB)" if a in ("downloaded", "saved_page")
                else "  (a file with this name exists; kept if identical)" if e.get("adopt") else "")
        print(f"  {LABEL[a]} {e['path']}{tail}")
    elif t == "done":
        if e["mode"] == "sync":
            print(f"\nDone: {e['files']} files, {e['bytes'] / 1_048_576:.1f} MB. "
                  "The backend indexes them automatically if it's running.")
    elif t == "deadlines":
        if "failed" in e:
            print(f"Deadlines: couldn't read the Blackboard calendar ({e['failed']})")
        elif "would_import" in e:
            print(f"Deadlines: {e['would_import']} on Blackboard")
        else:
            print(f"Deadlines: {e['new']} new, {e['updated']} updated, {e['removed']} removed on Blackboard")
    elif t == "login_waiting":
        print("Log in to Blackboard in the browser window that just opened. Waiting…", flush=True)
    elif t == "logged_in":
        print("Logged in.", flush=True)
    elif t == "login_required":
        print("Blackboard session expired. Run once without --headless to log in.")
    elif t == "error":
        print(e["message"])


def json_event(e: dict) -> None:
    print(json.dumps(e, ensure_ascii=False), flush=True)


def my_courses(api: BlackboardAPI) -> list[dict]:
    me = api.get(f"{API}/users/me?fields=id")
    rows = paged(api, f"{API}/users/{me['id']}/courses?expand=course&limit=100"
                      "&fields=availability.available,course.id,course.courseId,course.name,course.availability.available")
    return [
        r["course"] for r in rows
        if r.get("course") and (r.get("availability") or {}).get("available") != "No"
        and (r["course"].get("availability") or {}).get("available") != "No"
    ]


def selected(course: dict, folder: str | None, only: str | None) -> bool:
    """Synced this run: mapped to a folder, and matching --course if given."""
    return folder is not None and (
        not only or only.casefold() in (folder.casefold(), clean_course_name(course["name"]).casefold()))


def run(api: BlackboardAPI, *, probe: bool, dry_run: bool, only: str | None, include_unmapped: bool,
        emit=print_event) -> int:
    s = get_settings()
    inbox = s.inbox
    folders = sorted(p.name for p in inbox.iterdir() if p.is_dir())
    courses = my_courses(api)

    mapping: list[tuple[dict, str | None]] = []
    for c in sorted(courses, key=lambda c: c["name"]):
        folder = match_folder(c, folders, s.blackboard_course_map)
        if folder is None and include_unmapped:
            folder = safe_segment(clean_course_name(c["name"]))
        mapping.append((c, folder))

    mode = "probe" if probe else "preview" if dry_run else "sync"
    emit({"type": "courses", "probe": probe,
          "courses": [{"name": clean_course_name(c["name"]), "folder": folder} for c, folder in mapping]})
    if probe:
        emit({"type": "done", "mode": mode, "files": 0, "bytes": 0})
        return 0

    state = load_state()
    total_new = total_bytes = 0
    for c, folder in mapping:
        if not selected(c, folder, only):
            continue
        skipped: Counter = Counter()
        files = list(walk(api, c["id"], skipped, folder))
        plan = plan_course(files, inbox / folder, state, inbox)
        emit({"type": "course", "folder": folder, "files": len(files), "to_download": len(plan.download),
              "unchanged": plan.unchanged, "deleted_locally": plan.deleted_locally,
              "skipped": dict(skipped.most_common())})
        for f, target, adopt in plan.download:
            rel = target.relative_to(inbox).as_posix()
            if dry_run:
                emit({"type": "file", "folder": folder, "path": rel, "adopt": adopt,
                      "action": "would_save_page" if f.text else "would_download"})
                continue
            try:
                if f.text is not None:
                    data = f.text.encode("utf-8")
                else:
                    data = api.download(f.url or f"{API}/courses/{f.course_id}/contents/{f.content_id}"
                                                 f"/attachments/{f.attachment_id}/download")
            except Exception as e:  # keep going; the next run retries it
                emit({"type": "file", "folder": folder, "path": rel, "action": "failed", "error": str(e)})
                continue
            if adopt:
                if target.read_bytes() == data:
                    state[f.key] = {"path": rel, "modified": f.modified}
                    save_state(state)
                    emit({"type": "file", "folder": folder, "path": rel, "action": "already_had"})
                    continue
                target = with_id(target, f)
                rel = target.relative_to(inbox).as_posix()
            write_atomic(target, data)
            state[f.key] = {"path": rel, "modified": f.modified}
            save_state(state)
            total_new += 1
            total_bytes += len(data)
            emit({"type": "file", "folder": folder, "path": rel, "kb": max(1, len(data) // 1024),
                  "action": "saved_page" if f.text else "downloaded"})
    try:  # a calendar problem never fails the file sync
        emit(planner_bb.import_deadlines(api, {c["id"]: f for c, f in mapping if selected(c, f, only)},
                                         dry_run=dry_run))
    except Exception as e:  # noqa: BLE001
        emit({"type": "deadlines", "failed": str(e)})
    emit({"type": "done", "mode": mode, "files": total_new, "bytes": total_bytes})
    return 0


# --- browser session --------------------------------------------------------


class PlaywrightAPI:
    """REST calls made with the cookies of a real, user-logged-in browser profile."""

    def __init__(self, headless: bool = False):
        from playwright.sync_api import sync_playwright

        s = get_settings()
        self.base = s.blackboard_url.rstrip("/")
        self.delay = s.blackboard_delay
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel=s.blackboard_browser, headless=headless, no_viewport=True
        )
        self._last = 0.0
        if COOKIES_FILE.exists():
            self.ctx.add_cookies(json.loads(COOKIES_FILE.read_text(encoding="utf-8")))

    def _save_cookies(self) -> None:
        COOKIES_FILE.write_text(json.dumps(self.ctx.cookies()), encoding="utf-8")

    def ensure_login(self, headless: bool = False, timeout_s: int = 600, emit=print_event) -> None:
        if self._status(f"{API}/users/me?fields=id") == 200:
            return
        if headless:
            raise LoginRequired
        page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        page.goto(f"{self.base}/ultra/course")
        emit({"type": "login_waiting"})
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(3)
            if self._status(f"{API}/users/me?fields=id") == 200:
                emit({"type": "logged_in"})
                self._save_cookies()
                return
        raise SystemExit("Timed out waiting for Blackboard login.")

    def _status(self, path: str) -> int:
        return self.ctx.request.get(self.base + path, max_redirects=0).status

    def _throttle(self) -> None:
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, path: str) -> dict:
        self._throttle()
        r = self.ctx.request.get(self.base + path)
        if not r.ok:
            raise APIError(path, r.status)
        return r.json()

    def download(self, path_or_url: str) -> bytes:
        self._throttle()
        url = path_or_url if path_or_url.startswith("http") else self.base + path_or_url
        r = self.ctx.request.get(url, timeout=120_000)
        if not r.ok:
            raise RuntimeError(f"download -> {r.status}")
        return r.body()

    def close(self) -> None:
        self._save_cookies()  # keeps any session refresh from this run
        self.ctx.close()
        self._pw.stop()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.sync.blackboard", description=__doc__.split("\n\n")[0])
    ap.add_argument("--probe", action="store_true", help="log in and show the course mapping; download nothing")
    ap.add_argument("--dry-run", action="store_true", help="list files that would be downloaded")
    ap.add_argument("--course", help="only sync this module (inbox folder or course name)")
    ap.add_argument("--include-unmapped", action="store_true", help="also sync courses without an inbox folder")
    ap.add_argument("--headless", action="store_true", help="no browser window (works while the saved session is valid)")
    ap.add_argument("--json", action="store_true", help="print one JSON event per line (used by the admin panel)")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # course names with accents on a cp1252 console
    emit = json_event if args.json else print_event
    try:
        api = PlaywrightAPI(headless=args.headless)
    except Exception as e:  # noqa: BLE001 -- browser missing, profile locked by another run, ...: report, don't crash
        emit({"type": "error", "message": f"Couldn't start the browser: {e}"})
        return 1
    try:
        api.ensure_login(headless=args.headless, emit=emit)
        return run(api, probe=args.probe, dry_run=args.dry_run, only=args.course,
                   include_unmapped=args.include_unmapped, emit=emit)
    except LoginRequired:
        emit({"type": "login_required"})
        return 3
    except SystemExit as e:
        emit({"type": "error", "message": str(e)})
        return 1
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
