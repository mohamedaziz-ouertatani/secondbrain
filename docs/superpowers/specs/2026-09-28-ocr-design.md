# OCR for image-only pages, slides and pictures

Date: 2026-09-28. Status: approved in chat, awaiting spec review.

## Why

Measured on the current inbox:
- **40 of 214 PDF pages** have fewer than 25 words and an image. Most are the Deep Learning decks exported to PDF: `ch5_transformers` (19/34 pages) and `ch6_LLM` (17/35).
- **21 of 274 slides** are a picture with fewer than 15 words. Most are DevOps workshop screenshots (terminal commands, Jenkins screens), plus 8 slides in the CSR defense deck.
- No file is fully scanned, so the Library shows no unreadable files. The gap is images *inside* otherwise-readable files.

## Decisions

- **Engine:** MuPDF's built-in Tesseract, through PyMuPDF (`Page.get_textpage_ocr`). **No system install.** It needs only language data files.
- **Language data:** `eng`, `fra` and `ara` from `tesseract-ocr/tessdata_best` (Apache-2.0), 31 MB, in `backend/data/tessdata/` (git-ignored; already downloaded). `uv run python -m app.ingest.ocr --setup` downloads them again if missing.
- **Scope:**
  - PDF pages whose text layer has fewer than `ocr_min_words` (25) words and at least one image.
  - Slide and Word pictures of at least 300×150 px, skipping any picture whose bytes appear more than once in the same file (template logos).
- **OCR text joins the page's own text:** a PDF page, a slide, or the Word section the picture sits in. So citations keep pointing at the right page, slide or section.
- **Honesty:** chunks that contain OCR text carry `meta.ocr = true`, and their fiche shows an "OCR" tag.

## Measured in a spike (`ch5_transformers.pdf`)

- 4–5 s per page at 300 dpi.
- A chart page gives useful words ("Transformer Applications: Translation… BLEU… GNMT (RNN)… Transformer").
- A title page of logos and a photo gives mostly junk (`| 4”A 4 ny: As @`).

This leads to two rules:
- **Image areas only** (`full=False`), so the existing text layer isn't read twice.
- **A line filter:** an OCR line is kept only if it has at least 2 words of 3 or more letters or digits, and at least 60% of its non-space characters are letters or digits. Everything else is dropped. (With 2-letter words the junk line above would pass: "ny" and "As", 64% alphanumeric.)
- With `full=False`, MuPDF's text page holds both the existing text and the OCR text. Only lines that aren't already in the page's text layer are kept as OCR text.

## Components

### `app/ingest/ocr.py` (new)

- `available() -> bool`: `ocr_enabled` is on and every language in `ocr_languages` has a `.traineddata` file in `tessdata_dir()` (`backend/data/tessdata`).
- `clean(text: str) -> str`: applies the line filter and joins the kept lines with newlines.
- `ocr_page(page: pymupdf.Page) -> str`: `page.get_textpage_ocr(language=..., dpi=300, full=False, tessdata=...)`, then `clean()`.
- `ocr_image(data: bytes) -> str`: opens the image bytes with PyMuPDF (`pymupdf.open(stream=data)`), converts the image to a one-page PDF, runs `ocr_page(full=True)`, then `clean()`. Unreadable image formats (EMF/WMF) return `""`.
- `main()` / `--setup`: downloads any missing language files from the raw `tessdata_best` URLs into `tessdata_dir()`, and prints what it did.

### Parsers (`app/ingest/parse.py`)

- **PDF:** for each page with fewer than `ocr_min_words` words and at least one image, when `ocr.available()`, run `ocr_page`, append the result to that page's text, and record the page number in `Parsed.ocr_pages`.
- **PPTX:** per slide, collect picture shapes, including those inside groups, with pixel size of at least 300×150, excluding images whose SHA-1 occurs more than once across the whole deck. OCR each one and append the results to the slide text.
- **DOCX:** the same size and duplicate rules for inline pictures. The text is appended to the section that contains the picture.
- `Parsed` gains `ocr_pages: set[int]` (1-based page, slide or section numbers that received OCR text).
- If a picture's OCR fails, it's logged and skipped; the file is still ingested.

### Pipeline (`app/ingest/pipeline.py`)

- `PARSER_VERSION` becomes 4, so every file is re-read once.
- A chunk whose page is in `parsed.ocr_pages` gets `meta.ocr = true`.

### Settings (`app/config.py`)

- `ocr_enabled: bool = True`, `ocr_min_words: int = 25`, `ocr_languages: str = "eng+fra"`.
- The admin settings list them **read-only** ("Changing it means re-indexing everything").
- Arabic is off by default. Mixing `ara` into every page makes Latin text worse. A user with Arabic slides can set `ocr_languages: eng+fra+ara`.

### API and UI

- **Citations:** each citation includes `ocr: bool`, taken from the chunk's `meta`. The fiche shows an "OCR" tag next to the call number, with the title "Read from an image; may contain recognition errors".
- **`/admin/status`:** the `index` part gains `ocr: {available: bool, pages: int}`, where `pages` counts chunks with `meta.ocr`. The Status card's Index row adds "OCR on · N passages", or "OCR off: language data missing (run python -m app.ingest.ocr --setup)".

## Testing

- **`tests/test_ocr.py`** (skipped when the language data is missing):
  - `clean()` keeps real lines and drops junk. This part is a pure unit test and always runs.
  - A generated PDF (PyMuPDF): page 1 has a text layer; page 2 is only an image of rendered text ("docker compose up"). Parsing gives page 2 OCR text containing `docker` and `compose`, and `ocr_pages == {2}`. Page 1 is not OCR'd.
  - A generated `.pptx` (python-pptx) with one large picture of text and a small logo repeated on two slides: only the large picture is OCR'd.
  - `ocr_enabled: false`, or a missing tessdata folder, means no OCR and no error.
- **Pipeline:** an ingested OCR page's chunks carry `meta.ocr = true`.
- **Real files:** before and after for `ch5_transformers.pdf` (words per page) and one DevOps workshop deck. Ask "What commands are used in the Docker workshop?" in DEVOPS and check that OCR fiches are cited and tagged.

## Out of scope

Describing diagrams in words (that would need a vision model). OCR of scanned whole documents beyond the per-page rule. Handwriting.
