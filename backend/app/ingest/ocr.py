"""Text inside images, with MuPDF's built-in Tesseract. No system install: only the language data in
backend/data/tessdata. `python -m app.ingest.ocr --setup` downloads it."""

import logging
import re
import sys
from pathlib import Path

import pymupdf

from ..config import ROOT, get_settings

log = logging.getLogger(__name__)

LANG_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/{}.traineddata"
PAGE_DPI = 300
IMAGE_DPI = 150
_WORD = re.compile(r"[^\W_]{3,}")


def tessdata_dir() -> Path:
    return ROOT / "backend" / "data" / "tessdata"


def _langs() -> list[str]:
    return [lang for lang in get_settings().ocr_languages.split("+") if lang]


def available() -> bool:
    s = get_settings()
    return s.ocr_enabled and all((tessdata_dir() / f"{lang}.traineddata").is_file() for lang in _langs())


def clean(text: str) -> str:
    """Keep lines that read like words: 2+ words of 3+ letters/digits, and mostly letters/digits."""
    keep = []
    for line in text.splitlines():
        s = line.strip()
        chars = [c for c in s if not c.isspace()]
        if chars and len(_WORD.findall(s)) >= 2 and sum(c.isalnum() for c in chars) / len(chars) >= 0.6:
            keep.append(s)
    return "\n".join(keep)


def ocr_page(page: pymupdf.Page, full: bool = False, dpi: int = PAGE_DPI) -> str:
    """OCR text on a page that isn't already in its text layer (full=False reads only the images)."""
    tp = page.get_textpage_ocr(language=get_settings().ocr_languages, dpi=dpi, full=full,
                               tessdata=str(tessdata_dir()))
    have = {ln.strip() for ln in page.get_text("text").splitlines() if ln.strip()}
    new = [ln for ln in page.get_text("text", textpage=tp).splitlines() if ln.strip() and ln.strip() not in have]
    return clean("\n".join(new))


def image_size(data: bytes) -> tuple[int, int] | None:
    """Pixel size, or None for formats MuPDF can't decode (EMF/WMF)."""
    try:
        pix = pymupdf.Pixmap(data)
        return pix.width, pix.height
    except Exception:  # noqa: BLE001 -- unsupported image formats just aren't OCR'd
        return None


def ocr_image(data: bytes) -> str:
    try:
        with pymupdf.open(stream=data) as img:
            pdf = pymupdf.open("pdf", img.convert_to_pdf())
        with pdf:
            return ocr_page(pdf[0], full=True, dpi=IMAGE_DPI)
    except Exception:  # one bad picture must not fail the file
        log.warning("OCR failed on an image", exc_info=True)
        return ""


def setup() -> None:
    """Download any missing language data."""
    import httpx

    tessdata_dir().mkdir(parents=True, exist_ok=True)
    for lang in sorted({*_langs(), "eng", "fra", "ara"}):
        target = tessdata_dir() / f"{lang}.traineddata"
        if target.is_file():
            print(f"{lang}: already there")
            continue
        print(f"{lang}: downloading…", flush=True)
        with httpx.stream("GET", LANG_URL.format(lang), follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            tmp = target.with_suffix(".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
            tmp.replace(target)
    print(f"OCR language data in {tessdata_dir()}")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup()
    else:
        print(f"OCR {'available' if available() else 'unavailable'}; run with --setup to download language data")
