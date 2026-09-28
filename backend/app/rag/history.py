"""Past questions and answers: every /ask writes one query_log row, so that table is the history."""

from ..db import get_pool

_COLUMNS = "id, ts, question, params->>'course' AS course, answer, citations, citation_valid, latency_ms"


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
