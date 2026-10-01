# Sikimi

A local, offline knowledge base for your course materials and notes. You ask a question and get an answer written only from your files. Every claim links to the exact page it came from. It handles French, English and Arabic.

Everything runs on your machine with free, open-source parts: Ollama (Qwen + bge-m3), PostgreSQL + pgvector, FastAPI and Next.js.

## Setup (once)

Requirements: Docker Desktop, [Ollama](https://ollama.com) (native Windows install), [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
docker compose up -d
```

```bash
ollama pull qwen3:4b-instruct
```

```bash
ollama pull bge-m3
```

```bash
cd backend && uv sync
```

```bash
cd frontend && npm install
```

For OCR (text inside images), download the Tesseract language data once. It's about 31 MB (English, French and Arabic) and goes into `backend/data/tessdata/`, which Git ignores. Nothing is installed system-wide:

```bash
cd backend && uv run python -m app.ingest.ocr --setup
```

The first ingest downloads the bge-m3 tokenizer (~17 MB) once. After that, everything works offline.

## Run

```bash
cd backend && uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

Open http://localhost:3000. `GET http://localhost:8000/health` reports whether the database, Ollama and both models are ready.

## Adding material

Drop PDF, PPTX, DOCX, `.md` or `.txt` files into `inbox/<course>/`. The subfolder name becomes the course, e.g. `inbox/Probability 2/Serie 1.pdf`.

The backend watches the folder:
- New and changed files are ingested within a few seconds.
- Deleted files leave the index, and so does a deleted or renamed module folder (a renamed one is re-filed under its new name).
- **Text inside images is read by OCR** (Tesseract, built into PyMuPDF):
  - PDF pages with fewer than 25 words and an image (diagram-heavy slides exported to PDF);
  - pictures of at least 300×150 px in slide decks and Word files, such as screenshots of terminals and tools. Pictures repeated in a file, like template logos, are skipped.

  The OCR text joins its own page, slide or section, so citations still point to the right place. Lines that don't read like words are dropped. Fiches from OCR text carry an **OCR** tag, because recognition can make mistakes. Without the language data, OCR is off, and the admin System details say so.
- OCR makes indexing slower: re-reading the whole library took about 12 minutes, most of it on slide screenshots. A screenshot-heavy deck takes a while to appear after a sync.
- Arabic OCR is off by default, because mixing it in makes French and English worse. For Arabic slides, set `ocr_languages: eng+fra+ara` in `config.yaml`.

## History

Every question you ask is kept on the server, so it survives browser clears and works on any port.
- **Desk:** the 40 most recent questions are stacked under the answer, filtered to the open drawer.
- **History page** (`/history`, in the rail): every question, grouped by day, with a drawer filter, search over questions and answers, and "Load older questions". Click one to reopen it on the desk with its fiches.
- **Delete:** the bin button on a History row, a past card or the open answer. You get 5 seconds to undo, then the question is deleted from the database. The daily backup keeps a copy (see Backups below).
- **Rate and label:** 👍/👎 on an answer, and **Relevant?** on each fiche (unmarked → Relevant → Not relevant). Marks save immediately. A question with at least one fiche marked relevant joins the evaluation set (see Evaluation below).

## Planner

Notes, to-dos and events, in **Planner** on the rail.
- **Capture:**
  - **Where:** the line at the top of the Planner, or press **N** on any page (**Alt+N** while typing) for a popup that starts in the open drawer.
  - **What it understands:** one line, such as `DEVOPS TP due fri 23:59`, `exam Probability 2 12/01 9h` or `cours optim demain 9h-11h`. The reading shows under the line (kind, drawer, date) with the matched words underlined, and you can change any part before pressing Enter.
  - **How it reads:** by rules in code, not the model. French and English dates work, days come before months (`12/01` is 12 January), and a to-do without a time is due at 23:59.
  - **Words it knows:** a line starting with `note:` or `idea:` is always a note. Extra module nicknames go in `planner_aliases` in `config.yaml`.
- **Kinds:**
  - **Notes** have no date. Tick one when you're done with it: it moves to the Done group under your notes, still there to read.
  - **To-dos** have a checkbox and an optional due date.
  - **Events** have a start, and an end or all-day.
- **Blackboard deadlines:**
  - Every sync imports the due dates from Blackboard's calendar as to-dos. That's all Blackboard's calendar holds: exams and class times aren't there, so type those yourself.
  - Title and date follow Blackboard, while your ticks and notes stay yours.
  - A deadline Blackboard drops is kept and struck through, not deleted.
- **File into drawer:** a note stays out of your answers until you file it. Filing saves it as Markdown in `inbox/<drawer>/`, where it's indexed and cited like any other note. After that, editing it in the Planner rewrites the file.
- **Coming up:**
  - The desk and each drawer show overdue to-dos and the next 7 days.
  - The rail badge counts what's overdue or due today.
  - There are no notifications outside the app.
- **Backups:** planner items are in the daily backup.

## Admin panel

Click the status line at the foot of the rail ("Ready · qwen3:4b-instruct") to open `/admin`. It has four tabs; a yellow number on a tab counts the problems waiting there.
- **Overview:** what needs attention (services down, a Blackboard login or failed sync, a sync or backup that's overdue, files that couldn't be read, and too many invalid citations or refusals in the last 7 days), each linked to where it's fixed. Then the everyday actions (**Sync now**, **Back up now**, **Rescan inbox**, **Pause summaries**), five at-a-glance readings, and the system details: model and GPU share, reranker, VRAM, answer times, index, OCR and summaries.
- **Library:** counts per module, files that couldn't be read, **Re-index**, **Re-enrich**, **Exclude** and **Include**; tags and the vocabulary pass; and the Blackboard sync. See Syncing from Blackboard below.
- **Quality:** insights over 7 days, 30 days or all time (questions, refusals, invalid citations, answer times, the trend, per module, the problem questions, dense vs hybrid), and the evaluation. See Evaluation below.
- **Settings:** retrieval and answer settings, saved to `config.local.yaml`, applied from the next question with no restart. See Configuration below.

Every setting, measure and action says what it does, with a "How it works" note for the details.

## Summaries, concepts and tags

After a file is indexed, a background job has the local model write a short summary, 5–10 key concepts and 3–8 topic tags for it:
- **Library:** the summary shows as one line under each file, and the filter box also searches summaries and concepts.
- **Reader:** the full summary and concepts sit at the top, marked **generated** because a 4B model can get them wrong.
  - PDF pages and PowerPoint slides are shown as pictures, with the indexed text folded underneath. Slides need [LibreOffice](https://www.libreoffice.org/) (`winget install TheDocumentFoundation.LibreOffice`). Each deck is converted to PDF the first time it's opened, which takes a few seconds, and is cached in `backend/data/slides`. Without LibreOffice, slides show their text only.
  - **Ask while you read:** an Ask panel sits on the right of the reader. It answers from the open file by default (switch to its whole course), and a cited slide or page scrolls the reader to it. Hide it to a tab; on narrow windows it slides over the page. These questions are kept in History like the desk's.
- **Timing:** the job pauses while you're asking a question and during rescans, re-indexes and evaluation runs, so answers aren't slowed. Long files are summarised in parts, then combined. The first pass over the whole library takes a while; after that, only new and changed files are summarised.
- **Admin:**
  - the admin Overview shows progress under System details, with **Pause summaries** and **Resume summaries** among the everyday actions;
  - Library has **Re-enrich** per module, and lists the files that couldn't be summarised.
- **Tags:**
  - Similar tags in a module are merged into one (e.g. "ci-cd" into "ci/cd"), by bge-m3 similarity at `tag_merge_threshold` (0.85; at 0.80 unrelated tags such as "configuration" and "setup" merged).
  - A module's tags are merged once all its files are summarised.
  - The library's tag bar filters by topic. Picking more than one narrows the list further. Tags used by a single file sit behind "+N more", since about two-thirds of tags belong to one file.
  - Tags in the reader link to that filter.
- **Admin Tags:**
  - rename, merge two, or delete a tag, per module;
  - your edits are remembered, so a deleted tag doesn't come back and merged forms stay merged;
  - tags and your edits are in the daily backup; summaries aren't, because they can be regenerated.
- **Turning it off:** set `enrich_enabled: false` in `config.yaml`.

## Syncing from Blackboard

The sync downloads your course files and saves the text of Ultra pages as Markdown notes, with formulas kept as LaTeX. Pictures in a page (PNG, JPEG, GIF, WebP) are saved in a folder beside its note and shown in the reader; any Markdown note in the inbox can show pictures it links by a relative path the same way. Everything goes into the matching `inbox/<module>/` folder.

### From the admin panel

The **Blackboard sync** section in `/admin` does everything below without a terminal:
- Sync now, Sync this module, Preview (what would be downloaded) and Course mapping. Progress shows file by file, grouped by module, and you can cancel.
- **Automatic sync:** the backend syncs on its own every `sync_auto_days` days (default 7; 0 turns it off; editable under Settings · Blackboard). A sync from the command line counts too.
- **Session expired:** the panel and the rail footer say "log in needed", and automatic syncs pause. **Log in** opens an Edge window; sign in there and the session is saved.

### From the command line

```bash
cd backend && uv run python -m app.sync.blackboard --probe
```

This opens an Edge window for you to log in, then shows how your Blackboard courses map to inbox folders. It downloads nothing. After that:

```bash
cd backend && uv run python -m app.sync.blackboard --dry-run --headless
```

```bash
cd backend && uv run python -m app.sync.blackboard --headless
```

How it behaves:
- **Course matching:** courses match inbox folders by name, ignoring the class suffix such as `__5DS1`. Courses without a folder are skipped. Wrong matches can be fixed with `blackboard_course_map` in `config.yaml`.
- **What's downloaded:** only readable types (PDF, PPTX, DOCX, MD, TXT), and only when new or changed on Blackboard.
- **Nothing is deleted.** If you delete a synced file yourself, it isn't downloaded again unless it changes on Blackboard.
- **Login:** your session is saved in `backend/data/`, which Git ignores. When it expires, press **Log in** in the admin panel, or run once without `--headless`.
- **Run history:** the admin panel keeps the last 20 runs in `backend/data/sync-runs.json`.

## Configuration

`config.yaml` holds the models, chunk size, `top_k` and the relevance threshold. Settings are layered, highest first:
1. environment variables, then a `.env` file (see `.env.example`);
2. `config.local.yaml`, which the admin panel writes. It's ignored by Git, and **Reset** in the panel removes a key from it;
3. `config.yaml`;
4. the defaults in `backend/app/config.py`.

A setting fixed by an environment variable shows as locked in the panel. The embedding model and chunk sizes can't be changed from the panel, because changing them means re-indexing everything.

Retrieval has two modes, set with `retrieval_mode`:
- `dense` (default): vector search only.
- `hybrid`: vector search plus Postgres full-text search, fused with RRF. It's off by default because on French questions about English course pages it ranked the French exercise sheets above the course notes.

The reranker (see Reranker) reorders the candidates in either mode:
- `rerank` (on): a cross-encoder on the GPU reorders the `candidate_k` (20) candidates before the top `top_k` go to the model. Editable in the admin panel.
- `rerank_max_length` (384): tokens per question+passage pair. 512 doesn't fit beside the LLM in 4 GB of VRAM.
- `rerank_keep_alive` (30): minutes idle before the reranker leaves the GPU.
- `rerank_model_path` (`data/models/bge-reranker-v2-m3.fp16.onnx`): relative to `backend/`.

Two experiments with summaries are off by default, and editable in the admin panel. Neither helped in the evaluation (see Evaluation):
- `doc_boost` (0): ranks passages higher when their file's summary matches the question.
- `doc_context` (off): starts each passage the model reads with its file's summary.

To see what a change does to real questions, press **Compare** under Insights in the admin panel, or replay the query log from the command line:

```bash
cd backend && uv run python -m app.rag.compare
```

On a 4 GB GPU, keep the LLM around 4B parameters at Q4. A 7B model runs, but part of it spills over to the CPU.

## Query log

Every question is stored in the `query_log` table, including:
- the retrieved chunks and their scores (with dense and keyword ranks in hybrid mode);
- the answer, the citations and whether they validated;
- your rating and fiche labels.

The History page reads this table, and labelled rows feed the evaluation.

## Backups

The data a rescan can't rebuild is backed up once a day while the backend runs: the question log (with your labels), excluded files, and the evaluation set and its runs. Each backup is a gzipped JSON-lines file in `backend/data/backups/`, which Git ignores. The newest 30 are kept (`backup_keep`). The index itself isn't backed up, because a rescan rebuilds it from `inbox/`.

```bash
cd backend && uv run python -m app.admin.backup --list
```

```bash
cd backend && uv run python -m app.admin.backup --restore secondbrain-2026-09-28_211828.jsonl.gz
```

A restore only adds rows that are missing, such as deleted history. It never overwrites anything. Backups live on the same disk, so they protect against mistakes, not against losing the disk.

## Evaluation

Measures how often retrieval finds the right page, and optionally how well answers cite it. Everything stays in the database, never in the repository, because the questions quote your course material.

**The question set:**
- **Generated:** your local model writes a question for each sampled page, and that page is the right answer. Pages are sampled across modules in proportion to their size, with at least 5 per module. Questions that copy the passage are rejected. About 5 minutes for 150.
- **Yours:** questions where you marked at least one fiche relevant. Their right answers are the pages you marked.

```bash
cd backend && uv run python -m app.eval.generate --n 150
```

**A run** (also from the admin Evaluation section):

```bash
cd backend && uv run python -m app.eval.run
```

- The default run takes about 3 minutes. It retrieves 20 passages per question in dense and hybrid mode and reports:
  - **recall@1, @5 and @20:** the share of questions whose right page is first, in the top 5, or in the top 20;
  - **MRR:** the average of 1/rank of the right page;
  - **the refusal rate.**

  Results are broken down overall, per module, per language, and generated vs yours.
- `--full` (about 20 minutes) also answers every question with the current settings, without writing to the query log. It reports **citations valid**, **cited the right page** and the median answer time.

Every run is saved with the settings it used, so you can compare runs before and after a change. First baseline (137 generated questions):

| | Dense | Hybrid |
|---|---|---|
| recall@1 | 45% | 35% |
| recall@5 | 84% | 72% |
| recall@20 | 96% | 96% |
| MRR | 0.62 | 0.52 |

The full run (dense): citations valid 94%, cited the right page 68%, median answer 6.7 s.

**Summary experiments** (2026-09-29, the same 137 generated questions, dense retrieval). The summary boost adds `doc_boost` × the question's similarity to the file summary to each passage's score:

| doc_boost | recall@1 | recall@5 | MRR | EN recall@5 (119) | FR recall@5 (18) |
|---|---|---|---|---|---|
| 0 | 44.5% | 83.9% | 0.617 | 83.2% | 88.9% |
| 0.1 | 43.8% | 84.7% | 0.610 | 84.0% | 88.9% |
| 0.2 | 44.5% | 85.4% | 0.619 | 84.9% | 88.9% |
| 0.3 | 45.3% | 83.9% | 0.625 | 84.0% | 83.3% |

The best value, 0.2, puts the right page in the top 5 for 2 more questions out of 137, which is within noise.

File context in prompts (`doc_context`), in two full runs off vs on:
- citations valid: 95% vs 94%;
- cited the right page: 69% vs 70%;
- median answer: 7.0 s vs 8.9 s.

**Decision:** both stay off. Neither changes answers beyond noise, and file context makes answers 28% slower. Summaries earn their place in browsing and filtering, not in ranking. The right page is already in the top 20 for 96% of questions, so a reranker remains the better lead.

## Reranker

`bge-reranker-v2-m3`, exported to fp16 ONNX and run with ONNX Runtime on DirectML, reorders the 20 best dense candidates before the top 5 go to the model. It loads on the first question (a few seconds) and leaves the GPU after 30 idle minutes.

- **Refusals are unchanged:** the cosine `min_score` gate decides whether to answer. Each question's best reranker score is logged (`params.top_rerank_score` in the query log) so that a refusal gate can be tuned on real questions later.
- **It never breaks a question:** if the model file is missing, DirectML isn't available (it's Windows-only), or scoring fails, retrieval uses the plain order. The admin System details and `/health` say why.
- **The model file** is `backend/data/models/bge-reranker-v2-m3.fp16.onnx` (1.1 GB, not in Git). To build it, which needs about 200 MB of CPU PyTorch in a separate dependency group and the 2.2 GB model from Hugging Face:

```bash
cd backend && uv run --group export python -m app.rag.rerank_export
```

The script checks the fp16 file against the full-precision model on six question/passage pairs (English, French, Arabic, one off-topic) and refuses to save it if any score differs by more than 0.1. The current file differs by 0.07 on DirectML.

**Spike** (2026-09-29, the 137 generated questions, dense top 20 reranked, RTX 2050 with 4 GB):

| max_length | recall@1 | recall@5 | MRR | ms per question beside qwen3:4b |
|---|---|---|---|---|
| no reranker | 44.5% | 83.9% | 0.617 | – |
| 256 | 54.0% | 86.1% | 0.694 | – |
| 384 | 56.9% | 89.1% | 0.720 | ~900 |
| 512 | 56.9% | 90.5% | 0.721 | 4,380 (VRAM full) |

French recall@1 went from 44% to 72%.

**Evaluation** (2026-09-29, runs 9 and 10: the same 137 questions on the 109-file library, reranker off then on):

| | dense | reranked |
|---|---|---|
| recall@1 | 43.8% | 56.2% |
| recall@5 | 82.5% | 88.3% |
| MRR | 0.611 | 0.715 |
| French recall@1 (18) | 44.4% | 72.2% |
| cited the right page | 67.9% | 72.3% |
| citations valid | 94.9% | 95.6% |
| median answer, generation only | 6.95 s | 7.88 s |

The evaluation's answer time starts after retrieval. Reranking itself adds 0.88 s per question (median, measured separately), so the full wait goes from about 7.0 s to about 8.8 s. That's 0.3 s over the 1.5 s the design allowed. It stays on: ranking gains 12 points (28 on French questions) and right citations 4 points. `rerank_max_length: 256` roughly halves the reranker's time for about 3 points of recall.

## Tests

```bash
cd backend && uv run pytest
```

Database tests use a separate `secondbrain_test` database on the compose Postgres, and skip when it isn't running.

## Roadmap

- **v1 (done):** watch-folder ingestion and cited Q&A, Blackboard sync, OCR of images in PDFs, slides and Word files.
- **v2:** hybrid search (built, off by default; dense wins in the evaluation) and the bge-reranker-v2-m3 reranker. The reranker is on: fp16 ONNX on DirectML, 0.9 s per question; the right page first 44% → 56%, cited 68% → 72% (see Reranker). Document summaries, concepts and tags (done; they don't help ranking, see Evaluation).
- **v3:** chat history (done), the admin panel (done: status, library, settings, insights, Blackboard sync, evaluation), daily backups (done), related notes and flashcards.
- **v4:** the evaluation set (done: generated and labelled questions, retrieval and full runs), and a Chrome extension to save from Blackboard.
