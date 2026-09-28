"""Turn an Ultra page body (HTML) into a Markdown note plus the files embedded in it."""

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

# Below this much prose (after dropping file names), a page is just links/images: no note.
MIN_NOTE_CHARS = 60


@dataclass
class Embedded:
    key: str  # stable across runs (signed URL query strings change every time)
    name: str
    url: str


def _embedded_key(url: str) -> str:
    m = re.search(r"xid-(\d+_\d+)", url)
    if m:
        return f"xid-{m.group(1)}"
    return "url-" + hashlib.sha1(urlsplit(url).path.encode()).hexdigest()[:16]


def _latex(math: Tag) -> str:
    # Editors differ: encoding="application/x-tex" in some courses, "LaTeX" in others.
    ann = math.find("annotation", attrs={"encoding": re.compile("tex", re.IGNORECASE)})
    if ann:
        tex = ann.get_text().strip()
    else:
        for other in math.find_all("annotation"):
            other.decompose()
        tex = math.get_text(" ", strip=True)
    return f"$${tex}$$" if math.get("display") == "block" else f"${tex}$"


def convert(body: str, title: str, breadcrumb: list[str] | None = None) -> tuple[str | None, list[Embedded]]:
    """Returns (markdown note or None if the page has no real text, embedded files)."""
    soup = BeautifulSoup(body, "html.parser")
    files: list[Embedded] = []

    for a in soup.find_all(attrs={"data-bbfile": True}):
        try:
            meta = json.loads(a["data-bbfile"])
        except (ValueError, TypeError):
            meta = {}
        name = meta.get("fileName") or meta.get("linkName") or meta.get("alternativeText") or a.get_text(strip=True)
        url = a.get("href") or meta.get("resourceUrl") or meta.get("viewerUrl")
        if name and url and url.startswith("http"):
            files.append(Embedded(_embedded_key(url), name, url))
        a.replace_with(f"[{name}]" if name else "")  # keep the reference, drop the expiring URL

    for img in soup.find_all("img"):
        img.decompose()

    # Math → placeholders so markdownify doesn't escape the LaTeX (a_1 → a\_1).
    formulas: list[str] = []
    for math in soup.find_all("math"):
        formulas.append(_latex(math))
        math.replace_with(f"MATHPLACEHOLDER{len(formulas) - 1}X")

    # No escaping: the note is read by the retriever and the LLM, not rendered.
    md = markdownify(str(soup), heading_style="ATX", bullets="-", escape_underscores=False, escape_asterisks=False)
    md = re.sub(r"MATHPLACEHOLDER(\d+)X", lambda m: formulas[int(m.group(1))], md)
    md = md.replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    prose = re.sub(r"\[[^\]]*\]", "", md)
    if len(re.sub(r"\s", "", prose)) < MIN_NOTE_CHARS:
        return None, files
    trail = f"*{' › '.join(breadcrumb)}*\n\n" if breadcrumb else ""
    return f"# {title}\n\n{trail}{md}\n", files
