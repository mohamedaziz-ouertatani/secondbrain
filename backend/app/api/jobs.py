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
