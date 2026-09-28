"""Replay the questions in query_log through dense and hybrid retrieval and show what changes.

    cd backend && uv run python -m app.rag.compare [--limit N]
"""

import argparse
import sys

from ..db import get_pool
from .retrieve import keywords, retrieve


def _label(h: dict) -> str:
    where = h["label"] or (f"p.{h['page']}" if h["page"] is not None else "")
    return f"{h['title']} {where}".strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=50, help="most recent distinct questions to replay")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT question, course FROM (
                   SELECT DISTINCT ON (question, params->>'course') question, params->>'course' AS course, id
                   FROM query_log ORDER BY question, params->>'course', id DESC) q
               ORDER BY id DESC LIMIT %s""",
            (args.limit,),
        ).fetchall()

    changed = flipped = 0
    for r in rows:
        _, d_src = retrieve(r["question"], r["course"], mode="dense")
        h_all, h_src = retrieve(r["question"], r["course"], mode="hybrid")
        d_ids = {h["chunk_id"] for h in d_src}
        h_ids = {h["chunk_id"] for h in h_src}
        verdict = lambda src: "answer" if src else "refuse"
        print(f"\n{r['question']}" + (f"  [{r['course']}]" if r["course"] else ""))
        print(f"  keywords: {' '.join(keywords(r['question'])) or '-'}")
        print(f"  dense: {verdict(d_src)}   hybrid: {verdict(h_src)}   best cosine: "
              f"{max((h['score'] for h in h_all), default=0):.2f}")
        if bool(d_src) != bool(h_src):
            flipped += 1
        if d_ids != h_ids:
            changed += 1
        for h in h_src:
            mark = "+" if h["chunk_id"] not in d_ids else " "
            print(f"  {mark} {_label(h)[:70]:70}  cos {h['score']:.2f}  "
                  f"dense #{h['dense_rank'] or '-'}  kw #{h['lex_rank'] or '-'}")
        for h in d_src:
            if h["chunk_id"] not in h_ids:
                print(f"  - {_label(h)[:70]:70}  cos {h['score']:.2f}")

    print(f"\n{len(rows)} questions: {changed} with different passages, "
          f"{flipped} with a different answer/refuse decision")
    get_pool().close()


if __name__ == "__main__":
    main()
