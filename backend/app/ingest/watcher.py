"""Watch the inbox and (re)ingest files once they stop changing."""

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..config import get_settings
from .pipeline import ingest_file, is_supported, remove_file, rescan

log = logging.getLogger(__name__)

DEBOUNCE_S = 2.0
MAX_RETRIES = 5


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "InboxWatcher"):
        self.w = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # The worker decides ingest vs. remove by whether the path still exists.
        if event.event_type in ("created", "modified", "closed", "deleted", "moved"):
            self.w.touch(Path(event.src_path))
        if event.event_type == "moved":
            self.w.touch(Path(event.dest_path))


class InboxWatcher:
    def __init__(self) -> None:
        self.inbox = get_settings().inbox
        self._pending: dict[Path, tuple[float, int]] = {}  # path -> (last event time, retries)
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._observer = Observer()
        self._worker = threading.Thread(target=self._run, name="inbox-worker", daemon=True)

    def touch(self, path: Path, retries: int = 0) -> None:
        if not is_supported(path):
            return
        with self._cv:
            self._pending[path] = (time.monotonic(), retries)
            self._cv.notify()

    def start(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self._observer.schedule(_Handler(self), str(self.inbox), recursive=True)
        self._observer.start()
        self._worker.start()
        threading.Thread(target=self._initial_scan, name="inbox-rescan", daemon=True).start()
        log.info("watching %s", self.inbox)

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify()
        self._observer.stop()
        self._observer.join(timeout=5)

    def _initial_scan(self) -> None:
        try:
            log.info("startup rescan: %s", rescan())
        except Exception:
            log.exception("startup rescan failed")

    def _due(self) -> list[tuple[Path, int]]:
        now = time.monotonic()
        ready = [(p, r) for p, (t, r) in self._pending.items() if now - t >= DEBOUNCE_S]
        for p, _ in ready:
            del self._pending[p]
        return ready

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                self._cv.wait(timeout=0.5)
                ready = self._due()
            for path, retries in ready:
                self._process(path, retries)

    def _process(self, path: Path, retries: int) -> None:
        try:
            if path.exists():
                ingest_file(path)
            else:
                remove_file(path)
        except PermissionError:  # Windows: file still locked by the copying process
            if retries < MAX_RETRIES:
                self.touch(path, retries + 1)
            else:
                log.error("gave up on locked file %s", path)
        except Exception:
            log.exception("failed to process %s", path)
