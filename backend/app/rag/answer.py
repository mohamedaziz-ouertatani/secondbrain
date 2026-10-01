"""Question → retrieve → stream answer → validate citations → log. Yields (event, data) pairs."""

import logging
import time
from collections.abc import Iterator

from psycopg.types.json import Jsonb

from ..config import get_settings
from ..db import get_pool
from ..llm import busy, ollama
from ..llm.prompts import NOT_FOUND, build_messages
from .citations import validate
from .retrieve import retrieve

log = logging.getLogger(__name__)

SNIPPET_CHARS = 240


def ask(question: str, course: str | None = None, doc_id: int | None = None) -> Iterator[tuple[str, dict]]:
    """doc_id: answer from that one document (asked from its reader)."""
    with busy.answering():  # background enrichment keeps off the GPU until the stream ends or is closed
        yield from _ask(question, course, doc_id)


def _ask(question: str, course: str | None = None, doc_id: int | None = None) -> Iterator[tuple[str, dict]]:
    s = get_settings()
    t0 = time.perf_counter()
    candidates, sources = retrieve(question, course, doc_id=doc_id)
    reranked = [h["rerank_score"] for h in candidates if "rerank_score" in h]
    entry = {
        "question": question,
        "llm_model": s.llm_model,
        "embed_model": s.embed_model,
        "params": {"top_k": s.top_k, "min_score": s.min_score, "mode": s.retrieval_mode, "course": course,
                   **({"doc_id": doc_id} if doc_id else {}),
                   "rerank": "on" if reranked else "off", "rerank_max_length": s.rerank_max_length,
                   "top_rerank_score": round(max(reranked), 4) if reranked else None,
                   **({"candidate_k": s.candidate_k, "rrf_k": s.rrf_k} if s.retrieval_mode == "hybrid" else {})},
        "retrieved": [
            {"chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "page": h["page"],
             "score": round(float(h["score"]), 4), "rank": i, "used": h in sources,
             **{key: h[key] for key in ("dense_rank", "lex_rank") if key in h},
             **({"rrf": round(h["rrf"], 5)} if "rrf" in h else {}),
             **({"rerank_score": round(h["rerank_score"], 4)} if "rerank_score" in h else {})}
            for i, h in enumerate(candidates, start=1)
        ],
        "answer": None,
        "citations": [],
        "citation_valid": None,
    }

    if not sources:
        entry["answer"] = NOT_FOUND
        yield "token", {"text": NOT_FOUND}
    else:
        raw: list[str] = []
        try:
            for tok in ollama.chat_stream(build_messages(question, sources)):
                raw.append(tok)
                yield "token", {"text": tok}
        except ollama.OllamaError as e:
            entry["answer"] = "".join(raw)
            _log(entry, t0)
            yield "error", {"message": str(e)}
            return
        v = validate(ollama.strip_reasoning("".join(raw)), len(sources))
        citations = []
        for new_n, orig_n in enumerate(v.order, start=1):
            src = sources[orig_n - 1]
            citations.append({
                "n": new_n, "chunk_id": src["chunk_id"], "doc_id": src["doc_id"],
                "title": src["title"], "page": src["page"], "label": src["label"], "ocr": src["ocr"], "course": src["course"],
                "mime": src["mime"], "path": src["path"], "snippet": _snippet(src["text"]), "text": src["text"],
            })
        entry.update(answer=v.text, citations=citations, citation_valid=v.valid)
        if v.invalid:
            log.warning("model cited non-existent sources %s", v.invalid)

    log_id = _log(entry, t0)
    yield "done", {
        "answer": entry["answer"], "citations": entry["citations"],
        "citation_valid": entry["citation_valid"], "log_id": log_id,
    }


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"


def _log(entry: dict, t0: float) -> int | None:
    entry = {**entry, "latency_ms": int((time.perf_counter() - t0) * 1000)}
    try:
        with get_pool().connection() as conn:
            return conn.execute(
                """INSERT INTO query_log (question, llm_model, embed_model, params, retrieved, answer, citations, citation_valid, latency_ms)
                   VALUES (%(question)s, %(llm_model)s, %(embed_model)s, %(params)s, %(retrieved)s, %(answer)s, %(citations)s, %(citation_valid)s, %(latency_ms)s)
                   RETURNING id""",
                {**entry, "params": Jsonb(entry["params"]), "retrieved": Jsonb(entry["retrieved"]),
                 "citations": Jsonb(entry["citations"])},
            ).fetchone()["id"]
    except Exception:
        log.exception("failed to write query_log")
        return None
