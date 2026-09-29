"""Backups of what a rescan can't rebuild: query_log (questions, answers, citations, labels), excluded_paths,
the evaluation set and its runs, your tag vocabulary, and your planner notes, to-dos and events.

    uv run python -m app.admin.backup                  # back up now
    uv run python -m app.admin.backup --list           # list backups
    uv run python -m app.admin.backup --restore FILE   # add back rows that are missing; never overwrites

One gzipped JSON-lines file per backup in backend/data/backups; the newest `backup_keep` are kept.
The backend writes one when the newest is more than a day old (BackupScheduler).
"""

import datetime as dt
import gzip
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from ..config import ROOT, get_settings
from ..db import get_pool

log = logging.getLogger(__name__)

# table -> (primary key, jsonb columns)
TABLES = {
    "query_log": ("id", {"params", "retrieved", "citations", "labels"}),
    "excluded_paths": ("path", set()),
    "eval_questions": ("id", set()),
    "eval_runs": ("id", {"params", "metrics", "per_question"}),
    "tags": ("id", set()),         # before tag_aliases, which point to them
    "tag_aliases": ("id", set()),  # document_tags isn't backed up: the vocabulary pass rebuilds it
    "planner_items": ("id", set()),  # your notes, to-dos and events can't be regenerated
}
SEQUENCES = ("query_log", "eval_questions", "eval_runs", "tags", "tag_aliases", "planner_items")
PREFIX, SUFFIX = "secondbrain-", ".jsonl.gz"
DAY = 86_400
_COLUMN = re.compile(r"^[a-z_]+$")


def backup_dir() -> Path:
    return ROOT / "backend" / "data" / "backups"


def backups(d: Path | None = None) -> list[Path]:
    """Oldest first (names sort by time)."""
    d = d or backup_dir()
    return sorted(d.glob(f"{PREFIX}*{SUFFIX}")) if d.is_dir() else []


def _json_default(v):
    if isinstance(v, dt.datetime | dt.date):
        return v.isoformat()
    raise TypeError(f"can't back up a {type(v).__name__}")


def backup(d: Path | None = None) -> Path:
    """Write every row of the tables to a new backup file, then prune old ones."""
    d = d or backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')  # noqa: DTZ005 -- local time: names match your clock
    target = d / f"{PREFIX}{stamp}{SUFFIX}"
    tmp = target.with_name(target.name + ".tmp")
    counts = {}
    with get_pool().connection() as conn, gzip.open(tmp, "wt", encoding="utf-8") as f:
        for table, (key, _) in TABLES.items():
            counts[table] = 0
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}"):
                f.write(json.dumps({"table": table, "row": row}, ensure_ascii=False, default=_json_default) + "\n")
                counts[table] += 1
    os.replace(tmp, target)  # a crash never leaves half a backup under the real name
    prune(d)
    log.info("backup %s: %s", target.name, counts)
    return target


def counts_in(path: Path) -> dict[str, int]:
    counts = dict.fromkeys(TABLES, 0)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            counts[json.loads(line)["table"]] += 1
    return counts


def prune(d: Path | None = None) -> None:
    keep = max(1, get_settings().backup_keep)
    for old in backups(d)[:-keep]:
        old.unlink(missing_ok=True)


def restore(path: Path) -> dict[str, int]:
    """Insert the rows that are missing (by primary key); existing rows are left untouched."""
    inserted = dict.fromkeys(TABLES, 0)
    with get_pool().connection() as conn, conn.transaction(), gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            table = rec["table"]
            _, json_cols = TABLES[table]  # KeyError on a table we don't back up: refuse the file
            row = rec["row"]
            if not all(_COLUMN.match(c) for c in row):
                raise ValueError(f"unexpected column name in {path.name}")
            values = {c: Jsonb(v) if c in json_cols and v is not None else v for c, v in row.items()}
            cols = ", ".join(values)
            params = ", ".join(f"%({c})s" for c in values)
            try:
                with conn.transaction():  # a savepoint: one row that can't go back doesn't sink the restore
                    inserted[table] += conn.execute(
                        f"INSERT INTO {table} ({cols}) VALUES ({params}) ON CONFLICT DO NOTHING", values
                    ).rowcount
            except psycopg.errors.ForeignKeyViolation:
                log.warning("restore: skipped a %s row whose parent isn't there", table)
        for t in SEQUENCES:  # restored ids must not be handed out again
            conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), GREATEST((SELECT max(id) FROM {t}), 1))")
    log.info("restored from %s: %s", path.name, inserted)
    return inserted


def last_backup(d: Path | None = None) -> dict | None:
    files = backups(d)
    if not files:
        return None
    f = files[-1]
    st = f.stat()
    return {"name": f.name, "at": dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(),
            "bytes": st.st_size, "kept": len(files)}


def due(now: float | None = None, d: Path | None = None) -> bool:
    files = backups(d)
    return not files or (now or time.time()) - files[-1].stat().st_mtime >= DAY


class BackupScheduler:
    """Checks every hour (first check shortly after startup) and backs up when the newest backup is a day old."""

    def __init__(self, first_delay: float = 120, every: float = 3600):
        self.first_delay, self.every = first_delay, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="backup", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(self.first_delay):
            return
        while True:
            try:
                if due():
                    backup()
            except Exception:  # a failed backup must not kill the scheduler; retried next hour
                log.exception("backup failed")
            if self._stop.wait(self.every):
                return


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if "--list" in argv:
            for f in backups():
                print(f"{f.name}  {f.stat().st_size / 1024:.0f} KB  {counts_in(f)}")
            return 0
        if "--restore" in argv:
            i = argv.index("--restore")
            if i + 1 >= len(argv):
                print("usage: --restore FILE")
                return 2
            path = Path(argv[i + 1])
            if not path.is_file():
                path = backup_dir() / argv[i + 1]
            print(f"Added back: {restore(path)}")
            return 0
        f = backup()
        print(f"Backed up {counts_in(f)} to {f}")
        return 0
    finally:
        get_pool().close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
