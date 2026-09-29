"""Short prompts: small local models follow short, concrete instructions best."""

import re

from ..config import get_settings
from .lang import NAMES, detect

SYSTEM = """You answer questions using ONLY the numbered sources below.
Rules:
- Cite every claim with its source number in brackets, e.g. [1] or [2][3].
- Write every formula in LaTeX between dollar signs: $x^2$ inline, $$\\frac{{a}}{{b}}$$ on its own line.
- If the sources do not contain the answer, say you could not find it in the notes.
- Answer in {language}.
- Be concise."""

NOT_FOUND = "I couldn't find this in your notes."


def where(source: dict) -> str:
    """Human locator for a source: 'p. 3', 'slide 3', a Word section heading, or 'note'."""
    mime = source.get("mime", "")
    if mime == "application/pdf":
        return f"p. {source['page']}"
    if mime.endswith("presentationml.presentation"):
        return f"slide {source['page']}"
    return source.get("label") or "note"


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0][:200]


def format_context(sources: list[dict]) -> str:
    """sources: dicts with title, page, mime, label, text (and summary) — numbered from 1 in list order."""
    context = get_settings().doc_context == "on"

    def about(s: dict) -> str:
        return f"About this file: {first_sentence(s['summary'])}\n" if context and s.get("summary") else ""

    return "\n\n".join(
        f"[{i}] ({s['title']}, {where(s)})\n{about(s)}{s['text']}" for i, s in enumerate(sources, start=1)
    )


def build_messages(question: str, sources: list[dict]) -> list[dict]:
    system = SYSTEM.format(language=NAMES[detect(question)])
    return [
        {"role": "system", "content": f"{system}\n\nSources:\n\n{format_context(sources)}"},
        {"role": "user", "content": question},
    ]
