"""Dense retrieval over chunks (v2 adds hybrid + RRF + rerank here)."""

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama


def dense(question: str, k: int, course: str | None = None) -> list[dict]:
    qvec = ollama.embed([question])[0]
    with get_pool().connection() as conn:
        conn.execute("SET hnsw.ef_search = 100")
        return conn.execute(
            """SELECT c.id AS chunk_id, c.document_id AS doc_id, c.page, c.text, c.meta->>'label' AS label,
                      d.title, d.course, d.mime, 1 - (c.embedding <=> %(q)s) AS score
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE %(course)s::text IS NULL OR d.course = %(course)s
               ORDER BY c.embedding <=> %(q)s
               LIMIT %(k)s""",
            {"q": qvec, "k": k, "course": course},
        ).fetchall()


def retrieve(question: str, course: str | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (all candidates, those above min_score)."""
    s = get_settings()
    hits = dense(question, s.top_k, course)
    return hits, [h for h in hits if h["score"] >= s.min_score]
