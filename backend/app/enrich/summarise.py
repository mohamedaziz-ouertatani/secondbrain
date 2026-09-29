"""Summary, key concepts and raw tags for one document: one call for a short file, map-reduce for a long one."""

from collections.abc import Callable

from ..llm.lang import NAMES, detect
from ..llm.ollama import OllamaError

GROUP_TOKENS = 2500  # bge-m3 tokens of chunk text per call; leaves room in num_ctx 4096 for the prompt and reply
REDUCE_FANIN = 8     # part descriptions combined per reduce call
MAX_TAG_CHARS = 40

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "concepts", "tags"],
}
SYSTEM = (
    "You describe a file from a university student's course material, so they can see what it covers. "
    "Reply as JSON with: summary (3 to 5 sentences), concepts (5 to 10 key concepts, short noun phrases), "
    "tags (3 to 8 short topic labels of 1 to 3 words, general enough that other files could share them). "
    "Write the summary and concepts in {language}. Use only what the text says."
)
REDUCE_NOTE = " You get descriptions of consecutive parts of one file: describe the whole file."
STRICT = " Reply with JSON only, with exactly the keys summary, concepts and tags."
ONE = "File: {title}\n\n{text}"
PART = "File: {title}\nPart {i} of {n}.\n\n{text}"
PARTS = "File: {title}\n\n{parts}"

Chat = Callable[[list[dict], dict], dict]


class BadOutput(ValueError):
    """The model's reply wasn't usable, even after one stricter retry."""


def groups(chunks: list[dict], budget: int = GROUP_TOKENS) -> list[list[dict]]:
    """Consecutive chunks, at most `budget` tokens per group. A chunk is never split; an oversize one stands alone."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    used = 0
    for c in chunks:
        if cur and used + c["n_tokens"] > budget:
            out.append(cur)
            cur, used = [], 0
        cur.append(c)
        used += c["n_tokens"]
    if cur:
        out.append(cur)
    return out


def _dedupe(items: list[str], cap: int) -> list[str]:
    seen: set[str] = set()
    out = []
    for it in items:
        if it and it.lower() not in seen:
            seen.add(it.lower())
            out.append(it)
    return out[:cap]


def clean(out: dict) -> dict:
    summary = str(out.get("summary") or "").strip()
    concepts, tags = out.get("concepts"), out.get("tags")
    if not summary or not isinstance(concepts, list) or not isinstance(tags, list):
        raise BadOutput("the model's reply is missing a summary, concepts or tags")
    return {
        "summary": summary,
        "concepts": _dedupe([" ".join(str(c).split()) for c in concepts], 10),
        "tags": _dedupe([t for t in (" ".join(str(t).lower().split()) for t in tags) if len(t) <= MAX_TAG_CHARS], 8),
    }


def _call(chat: Chat, system: str, user: str) -> dict:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return clean(chat(messages, SCHEMA))
    except (BadOutput, OllamaError):
        messages[0] = {"role": "system", "content": system + STRICT}
        try:
            return clean(chat(messages, SCHEMA))
        except OllamaError as e:
            raise BadOutput(str(e)) from e


def _join(group: list[dict]) -> str:
    return "\n\n".join(c["text"] for c in group)


def _render(part: dict) -> str:
    return f"{part['summary']}\nConcepts: {', '.join(part['concepts'])}\nTags: {', '.join(part['tags'])}"


def summarise(title: str, chunks: list[dict], chat: Chat) -> dict:
    """{summary, concepts, tags} for a document's chunks (in order). Raises BadOutput."""
    if not chunks:
        raise BadOutput("no indexed text")
    system = SYSTEM.format(language=NAMES[detect(" ".join(c["text"] for c in chunks[:3]))])
    parts = groups(chunks)
    if len(parts) == 1:
        return _call(chat, system, ONE.format(title=title, text=_join(parts[0])))
    results = [_call(chat, system, PART.format(title=title, i=i, n=len(parts), text=_join(g)))
               for i, g in enumerate(parts, start=1)]
    while len(results) > 1:
        results = [
            _call(chat, system + REDUCE_NOTE,
                  PARTS.format(title=title, parts="\n\n".join(_render(r) for r in results[i:i + REDUCE_FANIN])))
            for i in range(0, len(results), REDUCE_FANIN)
        ]
    return results[0]
