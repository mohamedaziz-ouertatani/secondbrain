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

Drop PDFs, `.md` or `.txt` files into `inbox/<course>/`. The subfolder name becomes the course, e.g. `inbox/Reseaux/cours-tcp.pdf`.

The backend watches the folder:
- New and changed files are ingested within a few seconds.
- Deleted files leave the index.
- Scanned PDFs with no text layer are listed in the Library as not searchable. OCR is planned.

## Syncing from Blackboard

The sync script downloads your course files and saves the text of Ultra pages as Markdown notes, with formulas kept as LaTeX. Everything goes into the matching `inbox/<module>/` folder.

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
- **Login:** your session is saved in `backend/data/`, which Git ignores. When it expires, run once without `--headless` to log in again.

## Configuration

`config.yaml` holds the models, chunk size, `top_k` and the relevance threshold. Environment variables or a `.env` file override it; see `.env.example`.

On a 4 GB GPU, keep the LLM around 4B parameters at Q4. A 7B model runs, but part of it spills over to the CPU.

## Query log

Every question is stored in the `query_log` table, including the retrieved chunks and their scores, the answer, the citations and whether they validated. This becomes the evaluation set later.

## Tests

```bash
cd backend && uv run pytest
```

Database tests use a separate `secondbrain_test` database on the compose Postgres, and skip when it isn't running.

## Roadmap

- **v1 (done):** watch-folder ingestion and cited Q&A.
- **v2:** hybrid search (vector + full-text with RRF), the bge-reranker-v2-m3 reranker, and document tags/summaries.
- **v3:** related notes, flashcards and chat history.
- **v4:** a Chrome extension to save from Blackboard, and an eval set built from the query log.
