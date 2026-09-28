# Second Brain

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
- Scanned PDFs with no text layer are listed in the Drawer as not searchable. OCR is planned.

## History

Every question you ask is kept on the server, so it survives browser clears and works on any port.
- **Desk:** the 40 most recent questions are stacked under the answer, filtered to the open drawer.
- **History page** (`/history`, in the rail): every question, grouped by day, with a drawer filter, search over questions and answers, and "Load older questions". Click one to reopen it on the desk with its fiches.
- **Delete:** the bin button on a History row, a past card or the open answer. You get 5 seconds to undo, then the question is **deleted permanently**: it also leaves the query log below.

## Admin panel

Click the status line at the foot of the rail ("Ready · qwen3:4b-instruct") to open `/admin`:
- **Status:** database, Ollama and models, how much of the LLM is on the GPU and when it unloads, VRAM used, recent answer times, and index size.
- **Insights:** over 7 days, 30 days or all time, the number of questions, refusals, invalid citations and answer times. Also a daily trend, counts per module, the refused, invalid and slowest questions (each opens on the desk), and a dense vs hybrid comparison of your recent questions.
- **Library:** counts per module, files that couldn't be read, **Rescan inbox**, and **Re-index** a module or file even if unchanged. **Exclude** keeps a file on disk but out of your answers, and **Include** brings it back.
- **Blackboard sync:** Sync now, Sync one module, Preview and Course mapping, with live progress, Cancel and recent runs. See Syncing from Blackboard below.
- **Settings:** retrieval mode, passages per answer, refusal threshold, model, temperature, context window and keep-alive. They're saved to `config.local.yaml` and apply from the next question, with no restart. See Configuration below.

## Syncing from Blackboard

The sync downloads your course files and saves the text of Ultra pages as Markdown notes, with formulas kept as LaTeX. Everything goes into the matching `inbox/<module>/` folder.

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
- `hybrid`: vector search plus Postgres full-text search, fused with RRF. It's off by default because on French questions about English course pages it ranked the French exercise sheets above the course notes. It's meant to feed a reranker later.

To see what a change does to real questions, press **Compare** under Insights in the admin panel, or replay the query log from the command line:

```bash
cd backend && uv run python -m app.rag.compare
```

On a 4 GB GPU, keep the LLM around 4B parameters at Q4. A 7B model runs, but part of it spills over to the CPU.

## Query log

Every question is stored in the `query_log` table, including the retrieved chunks and their scores (with dense and keyword ranks in hybrid mode), the answer, the citations and whether they validated. The History page reads this table, and this becomes the evaluation set later. There is no backup: a question deleted from History is gone for good.

## Tests

```bash
cd backend && uv run pytest
```

Database tests use a separate `secondbrain_test` database on the compose Postgres, and skip when it isn't running.

## Roadmap

- **v1 (done):** watch-folder ingestion and cited Q&A, Blackboard sync.
- **v2:** hybrid search (built, off by default), the bge-reranker-v2-m3 reranker (parked: it orders passages well but takes 12–23 s per question on the CPU), and document tags/summaries.
- **v3:** chat history (done), the admin panel (done: status, library, settings, insights and Blackboard sync), related notes and flashcards.
- **v4:** a Chrome extension to save from Blackboard, and an eval set built from the query log.
