"""One index job at a time (rescan, re-index): a second request gets 409 instead of queueing behind the lock."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

_job = threading.Lock()


@contextmanager
def exclusive(what: str) -> Iterator[None]:
    if not _job.acquire(blocking=False):
        raise HTTPException(409, f"{what}: another rescan or re-index is running")
    try:
        yield
    finally:
        _job.release()


def try_acquire() -> bool:
    """Take the index-job slot without waiting (background jobs that aren't a request)."""
    return _job.acquire(blocking=False)


def release() -> None:
    _job.release()


def busy() -> bool:
    """Is an index job (rescan, re-index, evaluation) running? Background enrichment waits for it."""
    return _job.locked()
