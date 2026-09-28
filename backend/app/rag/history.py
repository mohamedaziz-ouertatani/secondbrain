"""Past questions and answers: every /ask writes one query_log row, so that table is the history."""

from psycopg.types.json import Jsonb

from ..db import get_pool

_COLUMNS = ("id, ts, question, params->>'course' AS course, answer, citations, citation_valid, latency_ms, "
            "feedback, labels")
UNSET = object()  # "leave feedback as it is", distinct from None ("clear it")


def _contains(q: str) -> str:
    """ILIKE pattern matching q literally (backslash is LIKE's default escape)."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_history(course: str | None = None, q: str | None = None, before: int | None = None, limit: int = 50) -> list[dict]:
    """Newest first. `before` is the last id of the previous page."""
    where, args = [], {"limit": max(1, min(limit, 200))}
    if course:
        where.append("params->>'course' = %(course)s")
        args["course"] = course
    if q:
        where.append("(question ILIKE %(q)s OR answer ILIKE %(q)s)")
        args["q"] = _contains(q)
    if before is not None:
        where.append("id < %(before)s")
        args["before"] = before
    sql = f"SELECT {_COLUMNS} FROM query_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with get_pool().connection() as conn:
        return conn.execute(sql + " ORDER BY id DESC LIMIT %(limit)s", args).fetchall()


def get_history(log_id: int) -> dict | None:
    with get_pool().connection() as conn:
        return conn.execute(f"SELECT {_COLUMNS} FROM query_log WHERE id = %s", (log_id,)).fetchone()


def delete_history(log_id: int) -> bool:
    """Permanent: the row also leaves any evaluation built from query_log."""
    with get_pool().connection() as conn:
        return conn.execute("DELETE FROM query_log WHERE id = %s", (log_id,)).rowcount > 0


def set_labels(log_id: int, feedback=UNSET, relevant: dict | None = None) -> dict | None:
    """Merge a rating (-1 | 1 | None) and per-citation relevance ({"<n>": True | False | None}; None clears)."""
    with get_pool().connection() as conn, conn.transaction():
        row = conn.execute("SELECT feedback, labels FROM query_log WHERE id = %s FOR UPDATE", (log_id,)).fetchone()
        if row is None:
            return None
        labels = dict(row["labels"] or {})
        rel = dict(labels.get("relevant") or {})
        for n, v in (relevant or {}).items():
            if v is None:
                rel.pop(n, None)
            else:
                rel[n] = bool(v)
        if rel:
            labels["relevant"] = rel
        else:
            labels.pop("relevant", None)
        conn.execute(
            "UPDATE query_log SET feedback = %s, labels = %s WHERE id = %s",
            (row["feedback"] if feedback is UNSET else feedback, Jsonb(labels) if labels else None, log_id),
        )
    return get_history(log_id)
