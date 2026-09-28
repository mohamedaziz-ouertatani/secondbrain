"""Evaluation runs: every question embedded once, 20 candidates in dense and hybrid mode, ranked by page.

    uv run python -m app.eval.run
"""

import sys

from psycopg.types.json import Jsonb

from ..config import get_settings
from ..db import get_pool
from ..ingest.pipeline import PARSER_VERSION
from ..llm import ollama
from ..llm.lang import detect
from ..rag.retrieve import retrieve_with_vector

K = 20
MODES = ("dense", "hybrid")


def rank_of(hits: list[dict], truth: set) -> int | None:
    for i, h in enumerate(hits[:K], start=1):
        if (h["path"], h["page"]) in truth:
            return i
    return None


def metrics(items: list[dict], mode: str) -> dict:
    n = len(items)
    if not n:
        return {"n": 0}
    ranks = [it[mode]["rank"] for it in items]
    out = {"n": n}
    for k in (1, 5, 20):
        out[f"recall@{k}"] = sum(r is not None and r <= k for r in ranks) / n
    out["mrr"] = sum(1 / r for r in ranks if r) / n
    out["refusal_rate"] = sum(it[mode]["refused"] for it in items) / n
    return out


def summarize(per_question: list[dict]) -> dict:
    def group(key: str) -> dict:
        keys = sorted({it[key] for it in per_question}, key=str)
        return {str(k): {m: metrics([it for it in per_question if it[key] == k], m) for m in MODES} for k in keys}

    return {"overall": {m: metrics(per_question, m) for m in MODES},
            "by_course": group("course"), "by_lang": group("lang"), "by_source": group("source")}


def questions() -> list[dict]:
    """Generated questions plus your labelled ones, each with its set of right (path, page)."""
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT id, question, course, lang, doc_path, page FROM eval_questions ORDER BY id").fetchall()
        labelled = conn.execute(
            """SELECT id, question, params->>'course' AS course, citations, labels FROM query_log
               WHERE labels ? 'relevant' ORDER BY id""").fetchall()
    out = [{"source": "generated", "id": r["id"], "question": r["question"], "course": r["course"],
            "lang": r["lang"], "truth": {(r["doc_path"], r["page"])}} for r in rows]
    for r in labelled:
        marks = r["labels"]["relevant"]
        truth = {(c["path"], c["page"]) for c in r["citations"] if marks.get(str(c["n"])) is True}
        if truth:  # a question with only "not relevant" marks has no right page to measure against
            out.append({"source": "real", "id": r["id"], "question": r["question"], "course": r["course"],
                        "lang": detect(r["question"]), "truth": truth})
    return out


def run(kind: str = "retrieval", progress=None, cancelled=None) -> int:
    qs = questions()
    vectors = ollama.embed([q["question"] for q in qs]) if qs else []
    per = []
    for i, (q, vec) in enumerate(zip(qs, vectors, strict=True), start=1):
        if cancelled and cancelled():
            break
        item = {k: q[k] for k in ("source", "id", "course", "lang")}
        for mode in MODES:
            hits, sources = retrieve_with_vector(vec, q["question"], None, mode, k=K)
            item[mode] = {"rank": rank_of(hits, q["truth"]), "refused": not sources}
        per.append(item)
        if progress:
            progress(i, len(qs))
    s = get_settings()
    params = {"questions": len(per), "top_k": s.top_k, "candidate_k": s.candidate_k, "rrf_k": s.rrf_k,
              "min_score": s.min_score, "embed_model": s.embed_model, "llm_model": s.llm_model,
              "parser_version": PARSER_VERSION, "retrieval_mode": s.retrieval_mode, "k": K}
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO eval_runs (kind, params, metrics, per_question) VALUES (%s, %s, %s, %s) RETURNING id",
            (kind, Jsonb(params), Jsonb(summarize(per)), Jsonb(per)),
        ).fetchone()["id"]


def _fmt(v) -> str:
    return "–" if v is None else f"{v:.2f}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    run_id = run(progress=lambda i, t: print(f"\r{i}/{t}", end="", flush=True))
    with get_pool().connection() as conn:
        m = conn.execute("SELECT metrics FROM eval_runs WHERE id = %s", (run_id,)).fetchone()["metrics"]
    print(f"\nrun {run_id}: {m['overall']['dense'].get('n', 0)} questions\n")
    print(f"{'':14}{'dense':>8}{'hybrid':>8}")
    for key in ("recall@1", "recall@5", "recall@20", "mrr", "refusal_rate"):
        print(f"{key:14}{_fmt(m['overall']['dense'].get(key)):>8}{_fmt(m['overall']['hybrid'].get(key)):>8}")
    print("\nrecall@5 by module")
    for course, v in m["by_course"].items():
        print(f"  {course[:30]:30}{_fmt(v['dense'].get('recall@5')):>8}{_fmt(v['hybrid'].get('recall@5')):>8}  n={v['dense']['n']}")
    print("\nby language")
    for lang, v in m["by_lang"].items():
        print(f"  {lang:30}{_fmt(v['dense'].get('recall@5')):>8}{_fmt(v['hybrid'].get('recall@5')):>8}  n={v['dense']['n']}")
    get_pool().close()


if __name__ == "__main__":
    main()
