"""Hybrid retrieval: dense (pgvector) + lexical (Postgres full-text) fused with RRF."""

import re
import unicodedata

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama

# The tsv column uses the 'simple' config, which keeps every word, so the query side drops
# function words and question words itself. Otherwise "qu'est-ce qu'un" matches everything.
STOPWORDS = frozenset("""
a an the and or but not no of to in on at by for from with without about into over under between
is are was were be been being am do does did done has have had can could should would will shall may might must
it its this that these those there here as if than then so such too very also just only more most less
i me my we our you your he she they them their his her
what which who whom whose when where why how whats
define definition explain describe give list tell show mean means meaning difference differences
le la les l un une des du de d au aux et ou mais ni ne pas plus moins que qu qui quoi dont où
est sont été être était étaient a ont avait avoir fait font
ce cet cette ces c se sa son ses leur leurs mon ma mes ton ta tes notre nos votre vos
je j tu il elle on nous vous ils elles me m te t lui y en s n
dans sur sous par pour avec sans entre vers chez comme si très aussi différence différences définition définir expliquer
quel quelle quels quelles comment pourquoi quand combien lequel laquelle
ما ماذا من هو هي هل كيف لماذا متى أين اين في على عن إلى الى مع و أو او ثم هذا هذه ذلك تلك التي الذي ان أن إن لا لم لن ما هم
""".split())  # noqa: SIM905


def keywords(question: str) -> list[str]:
    """Content words of a question, split roughly like Postgres' parser (underscores and hyphens separate)."""
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", question).lower())
    return list(dict.fromkeys(w for w in words if len(w) > 1 and w not in STOPWORDS))


_COLUMNS = """c.id AS chunk_id, c.document_id AS doc_id, c.page, c.text, c.meta->>'label' AS label,
              d.title, d.course, d.mime, d.path, 1 - (c.embedding <=> %(q)s) AS score"""
_COURSE = "(%(course)s::text IS NULL OR d.course = %(course)s)"


def dense(question: str, k: int, course: str | None = None) -> list[dict]:
    qvec = ollama.embed([question])[0]
    with get_pool().connection() as conn:
        return _dense(conn, qvec, k, course)


def _dense(conn, qvec, k: int, course: str | None) -> list[dict]:
    conn.execute("SET hnsw.ef_search = 100")
    return conn.execute(
        f"""SELECT {_COLUMNS}
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {_COURSE}
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s""",
        {"q": qvec, "k": k, "course": course},
    ).fetchall()


def _lexical(conn, qvec, terms: list[str], k: int, course: str | None) -> list[dict]:
    """Chunks matching any term, best ts_rank_cd first; all_terms marks chunks that contain every term."""
    if not terms:
        return []
    return conn.execute(
        f"""SELECT {_COLUMNS}, c.tsv @@ to_tsquery('simple', %(all)s) AS all_terms
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.tsv @@ to_tsquery('simple', %(any)s) AND {_COURSE}
            ORDER BY ts_rank_cd(c.tsv, to_tsquery('simple', %(any)s)) DESC, c.id
            LIMIT %(k)s""",
        {"q": qvec, "k": k, "course": course, "any": " | ".join(terms), "all": " & ".join(terms)},
    ).fetchall()


def fuse(dense_hits: list[dict], lexical_hits: list[dict], k: int) -> list[dict]:
    """Reciprocal rank fusion: each list adds 1/(k + rank). Ties go to the higher cosine."""
    fused: dict[int, dict] = {}
    for name, hits in (("dense_rank", dense_hits), ("lex_rank", lexical_hits)):
        for rank, h in enumerate(hits, start=1):
            f = fused.setdefault(h["chunk_id"], {**h, "dense_rank": None, "lex_rank": None, "rrf": 0.0})
            if "all_terms" in h:
                f["all_terms"] = h["all_terms"]
            f[name] = rank
            f["rrf"] += 1 / (k + rank)
    return sorted(fused.values(), key=lambda h: (-h["rrf"], -h["score"]))


def answerable(hits: list[dict], min_score: float) -> bool:
    """Worth asking the LLM: something is semantically close, or one chunk has every keyword."""
    return any(h["score"] >= min_score or h.get("all_terms") for h in hits)


def retrieve(question: str, course: str | None = None, mode: str | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (all candidates, the ones passed to the LLM)."""
    return retrieve_with_vector(ollama.embed([question])[0], question, course, mode)


def retrieve_with_vector(
    qvec, question: str, course: str | None = None, mode: str | None = None
) -> tuple[list[dict], list[dict]]:
    """retrieve() with the question already embedded, so one vector can serve both modes."""
    s = get_settings()
    mode = mode or s.retrieval_mode
    with get_pool().connection() as conn:
        if mode == "dense":
            hits = _dense(conn, qvec, s.top_k, course)
            return hits, [h for h in hits if h["score"] >= s.min_score]
        dense_hits = _dense(conn, qvec, s.candidate_k, course)
        lexical_hits = _lexical(conn, qvec, keywords(question), s.candidate_k, course)
    hits = fuse(dense_hits, lexical_hits, s.rrf_k)
    return hits, hits[: s.top_k] if answerable(hits, s.min_score) else []
