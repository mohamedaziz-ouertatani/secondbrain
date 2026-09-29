"""Query-log insights for the admin panel: health numbers, daily trend, problem lists, dense vs hybrid."""

from ..db import get_pool
from ..llm import ollama
from ..llm.prompts import NOT_FOUND
from ..rag.retrieve import retrieve_with_vector

PROBLEMS = {
    "refused": ("answer = %(nf)s", "id DESC"),
    "invalid": ("citation_valid IS false", "id DESC"),
    "slow": ("latency_ms IS NOT NULL", "latency_ms DESC, id DESC"),
}


def _since(days: int) -> str:
    return "ts >= now() - make_interval(days => %(days)s)" if days else "true"


def _ms(v) -> int | None:
    return None if v is None else int(v)


def summary(days: int, tz: str) -> dict:
    p = {"days": days, "tz": tz, "nf": NOT_FOUND}
    where = _since(days)
    with get_pool().connection() as conn:
        if not conn.execute("SELECT 1 FROM pg_timezone_names WHERE name = %s", (tz,)).fetchone():
            raise ValueError(f"unknown time zone: {tz}")
        head = conn.execute(
            f"""SELECT count(*) AS questions,
                       count(*) FILTER (WHERE answer = %(nf)s) AS refused,
                       count(*) FILTER (WHERE citation_valid IS false) AS invalid,
                       count(*) FILTER (WHERE answer IS NULL) AS failed,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_ms,
                       max(latency_ms) AS max_ms
                FROM query_log WHERE {where}""", p).fetchone()
        per_module = conn.execute(
            f"""SELECT params->>'course' AS course, count(*) AS questions,
                       count(*) FILTER (WHERE answer = %(nf)s) AS refused
                FROM query_log WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST""", p).fetchall()
        per_day = conn.execute(
            f"""SELECT (ts AT TIME ZONE %(tz)s)::date AS day, count(*) AS questions,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_ms
                FROM query_log WHERE {where} GROUP BY 1 ORDER BY 1""", p).fetchall()
    return {
        **head, "median_ms": _ms(head["median_ms"]), "max_ms": _ms(head["max_ms"]),
        "per_module": per_module,
        "per_day": [{"day": d["day"].isoformat(), "questions": d["questions"], "median_ms": _ms(d["median_ms"])}
                    for d in per_day],
    }


def problems(kind: str, days: int, limit: int) -> list[dict]:
    cond, order = PROBLEMS[kind]
    with get_pool().connection() as conn:
        return conn.execute(
            f"""SELECT id, ts, question, params->>'course' AS course, latency_ms FROM query_log
                WHERE {cond} AND {_since(days)} ORDER BY {order} LIMIT %(limit)s""",
            {"nf": NOT_FOUND, "days": days, "limit": limit},
        ).fetchall()


def _brief(h: dict) -> dict:
    return {"chunk_id": h["chunk_id"], "title": h["title"], "page": h["page"], "label": h["label"],
            "score": round(float(h["score"]), 3)}


def compare(limit: int = 20) -> dict:
    """Replay the most recent distinct questions through dense and hybrid retrieval, one embedding each."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT question, course FROM (
                   SELECT DISTINCT ON (question, params->>'course') question, params->>'course' AS course, id
                   FROM query_log ORDER BY question, params->>'course', id DESC) q
               ORDER BY id DESC LIMIT %s""",
            (limit,),
        ).fetchall()
    vectors = ollama.embed([r["question"] for r in rows]) if rows else []
    out, changed, flipped = [], 0, 0
    for r, qvec in zip(rows, vectors, strict=True):
        _, dense = retrieve_with_vector(qvec, r["question"], r["course"], "dense", rerank=False)
        _, hybrid = retrieve_with_vector(qvec, r["question"], r["course"], "hybrid", rerank=False)
        diff = {h["chunk_id"] for h in dense} != {h["chunk_id"] for h in hybrid}
        flip = bool(dense) != bool(hybrid)
        changed += diff
        flipped += flip
        out.append({
            "question": r["question"], "course": r["course"],
            "dense": [_brief(h) for h in dense], "hybrid": [_brief(h) for h in hybrid],
            "verdict_dense": "answer" if dense else "refuse",
            "verdict_hybrid": "answer" if hybrid else "refuse",
            "changed": diff,
        })
    return {"summary": {"questions": len(out), "changed": changed, "flipped": flipped}, "rows": out}
