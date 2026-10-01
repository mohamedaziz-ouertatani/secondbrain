"""Slides drawn as pictures: a deck is converted to PDF once (headless LibreOffice), cached by content.

The reader then renders slide N like PDF page N. Without LibreOffice, slides stay text-only.
"""

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config import ROOT
from app.ingest.pipeline import sha256_of

CONVERT_TIMEOUT = 180  # seconds; a long deck with big pictures takes a while
# Hidden slides too: the parser keeps them, so slide N of the PDF is slide N of the text.
PDF_FILTER = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'

# LibreOffice runs one conversion per profile at a time; one lock keeps it simple.
_lock = threading.Lock()
# (path, mtime, size) -> sha256, so serving each slide doesn't re-hash the deck
_digests: dict[tuple[str, int, int], str] = {}


def cache_dir() -> Path:
    return ROOT / "backend" / "data" / "slides"


def converter() -> str | None:
    """The LibreOffice executable, or None if it isn't installed."""
    found = shutil.which("soffice")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        exe = Path(base or "") / "LibreOffice" / "program" / "soffice.exe"
        if base and exe.is_file():
            return str(exe)
    return None


def convert(src: Path, out: Path) -> None:
    """src (.pptx) -> out (.pdf), through a private LibreOffice profile so an open LibreOffice doesn't block it."""
    profile = (cache_dir() / "profile").resolve().as_uri()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [converter(), f"-env:UserInstallation={profile}", "--headless", "--norestore",
             "--convert-to", PDF_FILTER, "--outdir", tmp, str(src)],
            check=True, capture_output=True, timeout=CONVERT_TIMEOUT,
        )
        made = Path(tmp) / f"{src.stem}.pdf"
        if not made.is_file():
            raise RuntimeError(f"LibreOffice made no PDF of {src.name}")
        shutil.move(made, out)


def _digest(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _digests:
        _digests[key] = sha256_of(path)
    return _digests[key]


def deck_pdf(path: Path) -> Path | None:
    """The deck as a PDF, converted on first use; None without LibreOffice."""
    out = cache_dir() / f"{_digest(path)}.pdf"
    if out.is_file():
        return out
    if not converter():
        return None
    with _lock:
        if not out.is_file():  # another request may have made it while this one waited
            out.parent.mkdir(parents=True, exist_ok=True)
            convert(path, out)
    return out
