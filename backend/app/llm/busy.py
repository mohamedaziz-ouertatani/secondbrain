"""Is a question being answered right now? Background LLM work (enrichment) waits while one is."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_count = 0
_lock = threading.Lock()


@contextmanager
def answering() -> Iterator[None]:
    global _count
    with _lock:
        _count += 1
    try:
        yield
    finally:
        with _lock:
            _count -= 1


def is_answering() -> bool:
    return _count > 0
