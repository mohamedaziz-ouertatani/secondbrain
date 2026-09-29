# Document summaries and tags

Date: 2026-09-29. Status: approved in chat, awaiting spec review.

## Why

Second Brain answers questions well, but it can't yet say what a file is *about*. Summaries, key concepts and topic tags per document are the first step from "a RAG" to knowledge organisation:
- **Browsing:** see what a file covers without opening it.
- **Filtering:** find every file on one topic.
- **Retrieval:** document-level context may rank passages better (to be measured).
- **Foundation:** related notes and the concept graph, the next cycles, build on this.

## Decisions

- **Generation runs in a background enrichment worker, after ingest.** Ingest is unchanged: files are searchable within seconds, and summaries arrive later. The worker yields the GPU to `/ask`.
- **Enrichment is keyed on the file hash.** A document needs enrichment when `enriched_sha IS DISTINCT FROM sha256`. A changed file is re-queued automatically. A forced re-index of an unchanged file is not.
- **Tags use a two-pass vocabulary.** The model proposes free tags per file. A vocabulary pass per module then merges near-duplicates into canonical tags by embedding similarity. Your renames, merges and deletes are recorded as aliases and survive later passes.
- **Summaries are labelled "generated"** in the UI, like the OCR tag, because a 4B model can get them wrong.
- **The retrieval changes ship off by default.** They're only turned on if the evaluation shows a gain, as with hybrid search.
- **Built in three stages**, each usable on its own:
  1. Schema, the worker, summaries and concepts, and display in the library and reader.
  2. The tag vocabulary pass, tag filters in the library and the admin Tags section.
  3. The retrieval experiment (`doc_boost`, `doc_context`) and an evaluation sweep.

## Data (migration `006_enrich.sql`)

```sql
ALTER TABLE documents
    ADD COLUMN concepts           JSONB,                 -- 5-10 short phrases
    ADD COLUMN raw_tags           JSONB,                 -- tags as the model proposed them, input to the vocabulary pass
    ADD COLUMN enriched_sha       TEXT,                  -- sha256 the enrichment was made from
    ADD COLUMN enrich_status      TEXT CHECK (enrich_status IN ('ok', 'error')),
    ADD COLUMN enrich_error       TEXT,
    ADD COLUMN summary_embedding  vector(1024);          -- stage 3
ALTER TABLE documents DROP COLUMN tags;                  -- unused v2 placeholder, replaced by document_tags
-- documents.summary (reserved in 001) holds the summary.

CREATE TABLE tags (
    id          BIGSERIAL PRIMARY KEY,
    course      TEXT,                                    -- NULL for loose notes
    name        TEXT NOT NULL,
    user_named  BOOLEAN NOT NULL DEFAULT false,          -- renamed or merged into by you: never auto-deleted
    UNIQUE NULLS NOT DISTINCT (course, name)
);
CREATE TABLE tag_aliases (
    id          BIGSERIAL PRIMARY KEY,                   -- a single-column key, so the backup can restore it
    course      TEXT,
    raw         TEXT NOT NULL,                           -- lowercased raw tag from the model
    tag_id      BIGINT REFERENCES tags(id) ON DELETE CASCADE,  -- NULL = you deleted it: drop this raw tag
    UNIQUE NULLS NOT DISTINCT (course, raw)
);
CREATE TABLE document_tags (
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);
```

- **Only `ok` and `error` are stored in `enrich_status`.** A document's shown state is derived:
  - `skipped` when `status <> 'ok'`;
  - `pending` when `enriched_sha IS DISTINCT FROM sha256`;
  - otherwise `enrich_status`.

  An error stores the hash too, so a failing file isn't retried in a loop. Re-enrich clears the hash.
- **Tags store no embedding.** Each vocabulary pass embeds the module's tag names, a few dozen on the CPU, so there's no vector to back up.

A deleted tag leaves an alias with a NULL `tag_id`, so the next pass doesn't bring that raw tag back.

## The enrichment worker (`app/enrich/`)

**Queue:**
- A daemon thread starts with the backend, like the auto-sync.
- It picks the oldest document (by `ingested_at`) with `status = 'ok'` and `enriched_sha IS DISTINCT FROM sha256`, and processes one document at a time. Excluded files are deleted from `documents`, so they never appear.
- A document with no chunks gets an error: "no indexed text".

**Summarising (`summarise.py`):**
- The document's chunks are read in order from the database, so nothing is re-parsed.
- **Short file** (up to about 3,000 tokens of chunk text): one LLM call returns JSON `{summary, concepts, tags}`.
- **Long file:** chunks are grouped into consecutive groups of up to about 3,000 tokens, without splitting a chunk. Each group gets a call that returns `{summary, concepts, tags}`. A final call combines the group outputs into one `{summary, concepts, tags}`. If the combined group summaries exceed the budget, they're combined in rounds.
- **Output:**
  - `summary`: 3–5 sentences, in the document's language (`documents.lang`);
  - `concepts`: 5–10 short phrases;
  - `tags`: 3–8 short topic labels.

  Everything is trimmed and lowercased where relevant, and duplicates are removed.
- Calls use the configured LLM with `format: json`, temperature 0.2 and the configured `num_ctx`.
- **Invalid JSON or missing keys:** retry once with a stricter prompt. If that fails too, `enrich_status = error` with the reason in `enrich_error`. The document stays fully searchable.

**Writing results:**
- Results are written in one transaction, guarded by `WHERE sha256 = <sha read at start>`. If the file changed meanwhile, the stale result is dropped and the document stays queued.
- The write sets `summary`, `concepts`, `raw_tags`, `enriched_sha` and `enrich_status = 'ok'`.
- Raw tags that already have an alias are linked in `document_tags` at once. New ones wait for the vocabulary pass.

**Yielding to answers:**
- `app/rag/answer.py` holds a process-wide "answering" counter while a question streams.
- The worker checks it before each LLM call and sleeps while it's non-zero. It also waits while an index job (rescan, re-index or evaluation) holds the shared job slot, so evaluation timings aren't skewed.
- At most one enrichment call is in flight, so a question waits for one call at worst.

**Ollama unavailable:** the worker backs off (5 s, doubling, capped at 5 min) and reports it in its state.

**Control:**
- The worker's state is kept in memory: running, paused or waiting for Ollama, plus the current file, done/total and the last error.
- `enrich_paused` is saved in `config.local.yaml` like other settings, so a pause survives a restart.
- Re-enrich a file or module: set `enriched_sha = NULL` for it, which re-queues it.

## The vocabulary pass (`app/enrich/vocab.py`)

It runs for a module when the module has no pending documents and at least one raw tag without an alias. It can also be triggered from admin.

1. Collect the module's raw tags that have no alias, with their frequency across documents.
2. Embed the module's existing tag names and the new raw tags with bge-m3 (on the CPU).
3. Go through the new raw tags, most frequent first. Link each to the closest tag (existing, or created earlier in this pass) when their cosine similarity is ≥ `tag_merge_threshold` (default 0.85, tuned on real tags during stage 2). Otherwise it becomes a new tag under its own name. Either way, record the alias.
5. Rebuild `document_tags` for the module from `raw_tags` and the aliases.
6. Delete tags with no documents, unless `user_named`.

The pass is idempotent: running it twice with no new raw tags changes nothing.

## API

**Public:**
- `GET /documents`: each row gains `summary`, `concepts`, `tags: [{id, name}]`, `enrich_status` and `enrich_error`.
- `GET /tags?course=`: `[{id, course, name, count}]`, sorted by count.

**Admin:**
- `GET /admin/enrich`: the worker state and counts per status.
- `POST /admin/enrich/pause` and `/resume`.
- `POST /admin/enrich/rerun`, with `{course}` or `{document_id}`.
- `POST /admin/tags/vocab`, with `{course}`: run the vocabulary pass now.
- `PATCH /admin/tags/{id}` with `{name}`: rename. It sets `user_named`. A name clash within the module returns 409.
- `POST /admin/tags/merge` with `{from, into}`: moves the document links and aliases to `into`, then deletes `from`.
- `DELETE /admin/tags/{id}`: sets the tag's aliases to NULL, then deletes it.

## UI

**Library (`/documents`):**
- Each file row shows a single-line summary excerpt under the title, with the full text on hover.
- **Tag bar** above the list:
  - with a drawer open, it shows that drawer's tags, by count;
  - with no drawer open, it shows tags grouped by module.
- Clicking a tag filters the list. More tags narrow it further (AND), and chips clear each one.
- The text search also matches summaries and concepts.
- **Enrichment markers:**
  - pending: a quiet "summarising…" marker;
  - error: "no summary", with the reason on hover;
  - skipped: nothing.

**Reader (`/documents/[id]`):** a header block with:
- the summary, marked "generated";
- the concepts;
- the tags as links to the library filtered by that tag.

**Admin:**
- **Status card:** an "Enrichment" line, e.g. "74/82 summarised · running", with Pause/Resume.
- **Tags section:**
  - a module selector and a table of name, count and merged raw forms;
  - actions: rename (inline), merge (select two, then Merge), delete, and "Run vocabulary pass".
- **Library section:**
  - a "Re-enrich" button per module;
  - a "Couldn't summarise" list with the reason and a per-file "Re-enrich" button.

**Desk:** unchanged.

## Stage 3: the retrieval experiment

Two settings, both editable in admin and both saved in evaluation run params:

- **`doc_boost`** (float, default 0):
  - Each summary is embedded with bge-m3 into `documents.summary_embedding` when it's written. A backfill covers existing summaries.
  - Dense retrieval scores a candidate as `chunk_similarity + doc_boost × cosine(question, summary_embedding)`, then re-sorts. A document without a summary contributes 0.
  - The `min_score` refusal check still uses the raw chunk similarity, so refusals don't change.
- **`doc_context`** (`off` | `on`, default `off`, a choice like `retrieval_mode`):
  - Each passage in the prompt gets a header line: `<title> — <first sentence of summary>`.
  - Citation numbering and validation are unchanged.

**Evaluation:**
- A retrieval-run sweep of `doc_boost` ∈ {0, 0.1, 0.2, 0.3}, compared with the dense baseline (recall@1 0.45, recall@5 0.84, MRR 0.62).
- One full run with `doc_context` on vs off.
- A setting becomes the default only if it improves recall@5 or recall@1 overall without lowering the French or English breakdown by more than 2 points.
- Results go in the README either way.

## Backups

`tags` and `tag_aliases` join the daily backup and restore, because your renames, merges and deletes can't be rebuilt. Two things aren't backed up:
- `document_tags`, which the vocabulary pass rebuilds from `raw_tags` and the aliases;
- summaries, concepts and embeddings, which are regenerable, like the index.

The restore inserts with `ON CONFLICT DO NOTHING`, and skips an alias whose tag couldn't be restored, instead of failing.

## Testing

pytest on the `secondbrain_test` database, with a fake LLM and embedder as in the eval tests:
- **Grouping:** a group never exceeds the budget and never splits a chunk; a short file makes one call; a long file does map then reduce.
- **JSON handling:** valid output; invalid then valid (one retry); invalid twice (`error` status, document still searchable).
- **Queueing:** a new file is queued; a changed sha is re-queued; an unchanged forced re-index isn't; excluded and non-ok documents aren't.
- **The stale-write guard:** the sha changes mid-enrichment, and nothing is written.
- **The vocabulary pass:** clustering at the threshold; existing aliases are respected; a deleted tag doesn't return; the pass is idempotent; unused tags are cleaned up but `user_named` ones are kept.
- **Tag endpoints:** rename (including a 409 clash), merge and delete.
- **Yielding:** the worker doesn't call the LLM while the answering counter is non-zero.
- **`doc_boost`:** scoring and re-sort order; refusals unchanged; 0 is identical to today.
- **The frontend:** verified in the browser preview (library filters, reader header, admin sections).

## Out of scope

- related notes;
- the concept graph;
- your own notes in the app;
- tags on desk fiches;
- per-section summaries.

These are later cycles, built on this data.
