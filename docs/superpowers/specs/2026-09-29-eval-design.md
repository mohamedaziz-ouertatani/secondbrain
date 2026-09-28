# Evaluation set

Date: 2026-09-29. Status: approved in chat, awaiting spec review.

## Why

Every retrieval decision so far (hybrid off, reranker parked, OCR on) was judged on about 20 real questions and a side-by-side comparison with no ground truth. An evaluation set turns "does this change help?" into numbers: recall@k and MRR for retrieval, and citation quality for answers.

## Decisions

- **Ground truth** has two sources:
  1. **Generated:** the local model writes a question from a sampled passage, and that passage's page is the right answer.
  2. **Your labels:** answers marked right or wrong and fiches marked relevant in the app, on your real questions.
- **The right answer is a document path and page, not a chunk id.** Re-indexing gives chunks new ids (the OCR re-read did), and the set must survive that. A retrieved passage is a hit when its `documents.path` and `page` match.
- **Everything lives in the database** (`eval_questions`, `eval_runs`, `query_log.labels`), **never in the repository**. The repo is public, and generated questions quote course material. The new tables join the daily backup.
- **Default run: retrieval only**, dense and hybrid side by side, about 1 minute. **Full run (optional):** also generates answers without writing to `query_log`, about 20 minutes.
- **Built in three stages**, each usable on its own:
  1. Generation, retrieval runs, the command line and the admin section.
  2. Labels on the desk, and labelled real questions in the evaluation.
  3. Full runs.

## Data (migration `005_eval.sql`)

```sql
CREATE TABLE eval_questions (
    id          BIGSERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    lang        TEXT NOT NULL,              -- fr | en | ar, from app.llm.lang.detect
    course      TEXT,                       -- the source document's module
    doc_path    TEXT NOT NULL,              -- ground truth: inbox-relative path ...
    page        INT NOT NULL,               -- ... and page / slide / section
    passage     TEXT NOT NULL,              -- the passage it was written from (for reading, and full runs)
    model       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE eval_runs (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,              -- retrieval | full
    params      JSONB NOT NULL,             -- settings in force: top_k, candidate_k, rrf_k, min_score, models, parser version
    metrics     JSONB NOT NULL,             -- see "Metrics"
    per_question JSONB NOT NULL             -- [{source, id, course, lang, dense: {rank, refused}, hybrid: {...}}]
);
ALTER TABLE query_log ADD COLUMN labels JSONB;  -- {"relevant": {"<n>": true|false}}; feedback holds -1 | 1 for the answer
```

`app/admin/backup.py` `TABLES` gains `eval_questions` (key `id`) and `eval_runs` (key `id`; jsonb `params`, `metrics`, `per_question`). `query_log.labels` is already covered with its table; `labels` joins its jsonb set. Restore advances every restored id sequence.

## Stage 1: generation and retrieval runs

### Generation (`app/eval/generate.py`)

- **Sampling:** passages with at least 60 tokens from documents with status `ok`. The quota per module is proportional to its chunk count, with at least 5 per module when it has that many. The draw is random but seeded (`--seed`, default 1) for repeatability. Each sampled page is used at most once.
- **Prompt:** `ollama.chat_json(messages, schema)`, a new non-streaming `/api/chat` call with `format` set to the JSON schema `{"question": string}`, `think: false` and temperature 0.3. System: write one question a student revising this module would ask, answerable from the passage alone, in the passage's language, without copying a phrase of more than 4 words, and without mentioning "the passage" or "the document". Rejected: an empty question, fewer than 4 words, more than 40 words, or 5 or more consecutive words copied from the passage (checked in code).
- **Stored:** each accepted row goes into `eval_questions` with `lang = detect(question)`.
- **Command line:** `uv run python -m app.eval.generate --n 150 [--seed 1] [--replace]`. `--replace` deletes the old generated set first; otherwise it adds pages that aren't in the set yet. Prints progress and a summary (accepted, rejected with reasons, per module).

### Retrieval run (`app/eval/run.py`)

- **Questions:** every row in `eval_questions`, plus (in stage 2) labelled real questions.
- **Per question:**
  - embed once (batched, `ollama.embed`);
  - retrieve **20** candidates in each mode with `retrieve_with_vector`, using `candidate_k` for dense as well, so recall@20 is defined;
  - find the rank (1-based) of the first candidate whose `(path, page)` is a right answer;
  - record `refused` from the same rule `/ask` uses (dense: best cosine under `min_score`; hybrid: `answerable()` is false).
- **Metrics per mode:** `recall@1`, `recall@5`, `recall@20` (the share of questions with rank ≤ k), `mrr` (mean of 1/rank, 0 when missed within 20) and `refusal_rate`. Each is reported overall, per course, per language, and per source (generated vs real).
- **Saved:** one `eval_runs` row with `kind = retrieval`. `params` records the settings, the embedding model and `PARSER_VERSION`.
- **Command line:** `uv run python -m app.eval.run [--full]` prints a table: rows are metrics, columns are dense and hybrid, followed by a per-course block.

### API and admin section

- `GET /admin/eval` returns `{questions: {generated, labelled}, job, runs: [last 10 without per_question], latest: <full run row>}`.
- `POST /admin/eval/generate` `{n}`, `POST /admin/eval/run` `{kind}` and `POST /admin/eval/cancel`.
- Jobs run in a background thread inside the backend, **one at a time**, sharing the index guard (`jobs.exclusive`) so they don't collide with a rescan. Progress is `{done, total, phase}`, polled by the page. Cancel stops at the next question.
- **The Evaluation section on `/admin`**, placed after Insights:
  - counts, the three buttons, and progress while a job runs;
  - the latest run as a table: recall@1/5/20, MRR and refusal rate for dense and hybrid, with the better value of each pair in bold;
  - a per-course table for the active mode;
  - run history, with each run's date, kind and key metrics against the previous run (±).

## Stage 2: labels

- `PUT /history/{id}/labels` `{feedback?: -1|1|null, relevant?: {"<n>": true|false|null}}` merges into `query_log.feedback` and `labels`, and returns the row.
- **Desk:**
  - the answer card's meta row gains 👍/👎 (icon buttons, toggled, `aria-pressed`);
  - each fiche gains a "Relevant?" toggle (✓ / ✗ / unset) in its actions row.
  - Saving is immediate; a failure shows the fiche's error text.
- **Evaluation:** a real question is included when at least one citation is marked relevant. Its right answers are those citations' `(path, page)`. Questions whose answer was marked 👎 with no relevant fiche are listed under the admin section's "Answers you marked wrong", for reading. They don't count in recall.

## Stage 3: full runs

- For each question: retrieve with the current settings, generate the answer with `build_messages` and `chat_stream` (without logging), and validate the citations with `citations.validate`.
- **Metrics:**
  - `citation_valid_rate`;
  - `cited_right_rate`: the share of answered questions whose valid citations include a right `(path, page)`;
  - the refusal rate;
  - median latency.
- Saved as a `kind = full` run. The UI shows these columns only for full runs.

## Testing

- **Unit:**
  - metric maths on hand-made rank lists (recall@k, MRR with misses, refusal rate);
  - the generation filters (length, copied 5-grams, empty);
  - quota allocation (proportional, minimum per module, total `n`).
- **Test DB:**
  - generation with a fake `chat_json` and the fake embedder stores rows with path and page, and skips short passages;
  - a retrieval run over two synthetic questions records the ranks;
  - the hit matching survives a forced re-index (new chunk ids);
  - the `/admin/eval` routes (409 while a job runs);
  - the labels route merge (stage 2);
  - a full run with a fake chat (stage 3);
  - the backup round trip now includes the eval tables.
- **Real:** generate 150 questions on your library, run a retrieval evaluation, and report dense vs hybrid overall and per module.

## Out of scope

Human-written gold sets, LLM-as-judge grading of answer quality, the Chrome extension, and changing retrieval defaults (that's decided from these numbers afterwards).
