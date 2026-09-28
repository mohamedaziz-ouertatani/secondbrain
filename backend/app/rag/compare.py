"""Replay the questions in query_log through dense and hybrid retrieval and show what changes.

    cd backend && uv run python -m app.rag.compare [--limit N]

The admin panel's "Compare" button runs the same comparison (app.admin.insights.compare).
"""

import argparse
import sys

from ..db import get_pool


def _label(h: dict) -> str:
    where = h["label"] or (f"p.{h['page']}" if h["page"] is not None else "")
    return f"{h['title']} {where}".strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=20, help="most recent distinct questions to replay (max 50)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    from ..admin.insights import compare

    out = compare(max(1, min(args.limit, 50)))
    for r in out["rows"]:
        dense_ids = {h["chunk_id"] for h in r["dense"]}
        hybrid_ids = {h["chunk_id"] for h in r["hybrid"]}
        print(f"\n{r['question']}" + (f"  [{r['course']}]" if r["course"] else ""))
        print(f"  dense: {r['verdict_dense']}   hybrid: {r['verdict_hybrid']}")
        for h in r["hybrid"]:
            print(f"  {'+' if h['chunk_id'] not in dense_ids else ' '} {_label(h)[:70]:70}  cos {h['score']:.2f}")
        for h in r["dense"]:
            if h["chunk_id"] not in hybrid_ids:
                print(f"  - {_label(h)[:70]:70}  cos {h['score']:.2f}")
    s = out["summary"]
    print(f"\n{s['questions']} questions: {s['changed']} with different passages, "
          f"{s['flipped']} with a different answer/refuse decision")
    get_pool().close()


if __name__ == "__main__":
    main()
