"""Page-aware chunking: chunks never cross pages, so each citation maps to one page."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)

TokenCounter = Callable[[str], int]

# Sentence ends for FR/EN (.!?) and Arabic (؟ ۔ ؛), followed by whitespace.
_SENTENCE_END = re.compile(r"(?<=[.!?؟۔؛])\s+")


@dataclass
class Chunk:
    page: int  # 1-based
    text: str
    n_tokens: int


@lru_cache
def bge_m3_counter() -> TokenCounter:
    """Token counter using bge-m3's tokenizer (downloaded once from HF, then read from cache offline)."""
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        try:
            path = hf_hub_download("BAAI/bge-m3", "tokenizer.json", local_files_only=True)
        except Exception:
            path = hf_hub_download("BAAI/bge-m3", "tokenizer.json")
        tok = Tokenizer.from_file(path)
        return lambda s: len(tok.encode(s, add_special_tokens=False).ids)
    except Exception as e:  # offline and not cached yet
        log.warning("bge-m3 tokenizer unavailable (%s); approximating tokens as chars/3", e)
        return lambda s: max(1, len(s) // 3)


def _units(text: str, count: TokenCounter, budget: int) -> list[tuple[str, int]]:
    """Split text into pieces that each fit the budget: paragraphs → sentences → word windows."""
    out: list[tuple[str, int]] = []
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        n = count(para)
        if n <= budget:
            out.append((para, n))
            continue
        for sent in (s.strip() for s in _SENTENCE_END.split(para)):
            if not sent:
                continue
            n = count(sent)
            if n <= budget:
                out.append((sent, n))
                continue
            # Summing per-word counts slightly overestimates, which keeps pieces under budget.
            buf: list[str] = []
            buf_tokens = 0
            for w in sent.split():
                wn = count(w)
                if buf and buf_tokens + wn > budget:
                    piece = " ".join(buf)
                    out.append((piece, count(piece)))
                    buf, buf_tokens = [], 0
                buf.append(w)
                buf_tokens += wn
            if buf:
                piece = " ".join(buf)
                out.append((piece, count(piece)))
    return out


def chunk_pages(
    pages: list[str], count: TokenCounter, max_tokens: int = 500, overlap: int = 80
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_no, text in enumerate(pages, start=1):
        units = _units(text, count, max_tokens)
        cur: list[tuple[str, int]] = []
        cur_tokens = 0
        for unit in units:
            if cur and cur_tokens + unit[1] > max_tokens:
                chunks.append(_make(page_no, cur, count))
                # carry trailing units as overlap, never a whole chunk's worth
                carry: list[tuple[str, int]] = []
                carried = 0
                for u in reversed(cur):
                    if carried + u[1] > overlap or carried + u[1] + unit[1] > max_tokens:
                        break
                    carry.insert(0, u)
                    carried += u[1]
                cur, cur_tokens = carry, carried
            cur.append(unit)
            cur_tokens += unit[1]
        if cur:
            chunks.append(_make(page_no, cur, count))
    return chunks


def _make(page: int, units: list[tuple[str, int]], count: TokenCounter) -> Chunk:
    text = "\n".join(u[0] for u in units)
    return Chunk(page=page, text=text, n_tokens=count(text))
