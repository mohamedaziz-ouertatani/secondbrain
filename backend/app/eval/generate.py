"""Generated evaluation questions: for sampled pages, the local model writes a question the page answers.
The page (document path + page number) is the ground truth.

    uv run python -m app.eval.generate --n 150 [--seed 1] [--replace]
"""

import argparse
import random
import re
import sys
from collections import Counter

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama
from ..llm.lang import detect

MIN_TOKENS = 60
MIN_PER_COURSE = 5
PASSAGE_CHARS = 1500
SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
SYSTEM = (
    "You write revision questions for a university student. You get one passage from their course material. "
    "Write ONE question the student could ask that this passage answers on its own. "
    "Write it in the same language as the passage. Do not copy any phrase longer than 4 words from the passage. "
    "Do not mention 'the passage', 'the text' or 'the document'. "
    'Reply as JSON: {"question": "..."}'
)
_TOKEN = re.compile(r"\w+")


def quotas(sizes: dict, n: int) -> dict:
    """Questions per course: at least MIN_PER_COURSE (capped by size), the rest proportional to size."""
    n = min(n, sum(sizes.values()))
    order = sorted(sizes, key=lambda c: (-sizes[c], str(c)))
    q = dict.fromkeys(sizes, 0)
    for _ in range(MIN_PER_COURSE):  # round-robin, so a small n still spreads across courses
        for c in order:
            if sum(q.values()) < n and q[c] < sizes[c]:
                q[c] += 1
    left = n - sum(q.values())
    if left > 0:
        cap = {c: sizes[c] - q[c] for c in sizes}
        total = sum(cap.values())
        share = {c: left * cap[c] / total for c in sizes}
        for c in sizes:
            q[c] += min(cap[c], int(share[c]))
        for c in sorted(sizes, key=lambda c: -(share[c] - int(share[c]))):  # largest remainders
            if sum(q.values()) < n and q[c] < sizes[c]:
                q[c] += 1
        for c in order:  # anything still missing, where there's room
            while sum(q.values()) < n and q[c] < sizes[c]:
                q[c] += 1
    return q


def reject_reason(question: str, passage: str) -> str | None:
    words = question.split()
    if not words:
        return "empty"
    if len(words) < 4:
        return "too short"
    if len(words) > 40:
        return "too long"
    q, p = _TOKEN.findall(question.lower()), _TOKEN.findall(passage.lower())
    grams = {tuple(p[i:i + 5]) for i in range(len(p) - 4)}
    if any(tuple(q[i:i + 5]) in grams for i in range(len(q) - 4)):
        return "copies the passage"
    return None


def _pages(conn, skip: set) -> dict:
    """course -> [(path, page, text)], one passage per page (its first long chunk)."""
    rows = conn.execute(
        """SELECT DISTINCT ON (d.path, c.page) d.path, c.page, c.text, d.course
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE d.status = 'ok' AND c.n_tokens >= %s
           ORDER BY d.path, c.page, c.ord""",
        (MIN_TOKENS,),
    ).fetchall()
    by_course: dict = {}
    for r in rows:
        if (r["path"], r["page"]) not in skip:
            by_course.setdefault(r["course"], []).append((r["path"], r["page"], r["text"]))
    return by_course


def generate(n: int = 150, seed: int = 1, replace: bool = False, chat=None, progress=None, cancelled=None) -> dict:
    chat = chat or ollama.chat_json
    model = get_settings().llm_model
    with get_pool().connection() as conn:
        if replace:
            conn.execute("DELETE FROM eval_questions")
        asked = {(r["doc_path"], r["page"]) for r in conn.execute("SELECT doc_path, page FROM eval_questions")}
        pool = _pages(conn, asked)
    rng = random.Random(seed)
    chosen = []
    for course, want in quotas({c: len(p) for c, p in pool.items()}, n).items():
        pages = sorted(pool[course])
        rng.shuffle(pages)
        chosen += [(course, *p) for p in pages[:want]]

    rejected: Counter = Counter()
    per_course: Counter = Counter()
    for i, (course, path, page, text) in enumerate(chosen, start=1):
        if cancelled and cancelled():
            break
        passage = text[:PASSAGE_CHARS]
        try:
            out = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": passage}], SCHEMA)
            question = str(out.get("question", "")).strip()
        except ollama.OllamaError:
            rejected["model error"] += 1
            continue
        finally:
            if progress:
                progress(i, len(chosen))
        reason = reject_reason(question, passage)
        if reason:
            rejected[reason] += 1
            continue
        with get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO eval_questions (question, lang, course, doc_path, page, passage, model)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (doc_path, page) DO NOTHING""",
                (question, detect(question), course, path, page, passage, model),
            )
        per_course[course] += 1
    return {"accepted": sum(per_course.values()), "rejected": dict(rejected), "per_course": dict(per_course)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--replace", action="store_true", help="delete the generated set first")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = generate(args.n, args.seed, args.replace,
                   progress=lambda i, t: print(f"\r{i}/{t}", end="", flush=True))
    print(f"\n{out['accepted']} questions added; rejected: {out['rejected'] or 'none'}")
    for c, k in sorted(out["per_course"].items(), key=lambda x: str(x[0])):
        print(f"  {c or '(no module)'}: {k}")
    get_pool().close()


if __name__ == "__main__":
    main()
