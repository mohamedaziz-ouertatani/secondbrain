# Admin panel, part 2: Settings + Insights

Date: 2026-09-28. Status: approved in chat, awaiting spec review.

Part 1 (Status + Library) is shipped. Part 3 (Blackboard sync) follows.

## Decisions

- Settings edited in the panel are saved to a **git-ignored `config.local.yaml`** next to `config.yaml`. The panel never rewrites `config.yaml`.
- Precedence becomes: **env vars > `.env` > `config.local.yaml` > `config.yaml` > defaults.** A key set by the environment is shown locked.
- Changes apply **without a restart**: saving clears the `get_settings()` cache, so the next request reads the new values.
- Insights come from `query_log` alone. There is no new storage.

## Settings

### Loading (`app/config.py`)

- `LOCAL_CONFIG = ROOT / "config.local.yaml"` is a module-level path, so tests can point it elsewhere.
- `settings_customise_sources` returns `(init, env, dotenv, Yaml(LOCAL_CONFIG), Yaml(config.yaml))`. It reads `LOCAL_CONFIG` at call time. A missing file is skipped (pydantic-settings already ignores YAML files that don't exist).
- `.gitignore` gains `config.local.yaml`.

### Editable keys (`app/admin/settings.py`)

| Group | Key | Control | Validation |
|---|---|---|---|
| Retrieval | `retrieval_mode` | choice `dense` / `hybrid` | one of the two |
| Retrieval | `top_k` | integer | 1–10 |
| Retrieval | `candidate_k` | integer | 5–100, and ≥ `top_k` |
| Retrieval | `rrf_k` | integer | 1–200 |
| Retrieval | `min_score` | number | 0–1 |
| Answers | `llm_model` | choice from Ollama's pulled models (`/api/tags`, excluding the embed model) | must be pulled |
| Answers | `temperature` | number | 0–1.5 |
| Answers | `num_ctx` | integer | 1024–32768 |
| Answers | `llm_keep_alive` | text | a duration like `30m`, `2h`, `0`, or `-1` (regex `^(-1|0|\d+[smh])$`) |

These are shown **read-only**, each with its reason:
- `embed_model`, `embed_dim`, `chunk_tokens`, `chunk_overlap`: changing them means re-indexing everything.
- `database_url`, `ollama_url`, `watch_dir`: they need a restart.
- The Blackboard settings: part 3.

`retrieval_mode` gets a pydantic `Literal["dense", "hybrid"]` type in `Settings`, so a bad value in any source fails loudly.

### Source of a value

For each key, the source is:
- `env` if `<KEY>` (upper case) is in the process environment or the `.env` file;
- otherwise `local` if the key is in `config.local.yaml`;
- otherwise `config` if it's in `config.yaml`;
- otherwise `default`.

### API

- `GET /admin/settings` returns groups of rows:

  ```json
  {"groups": [{"name": "Retrieval", "rows": [
     {"key": "top_k", "value": 5, "source": "config", "editable": true, "control": "int", "min": 1, "max": 10,
      "help": "Passages sent to the model", "locked_by": null}]}],
   "readonly": [{"key": "embed_model", "value": "bge-m3", "reason": "Changing it means re-indexing everything"}]}
  ```

  `control` is `int` | `float` | `choice` | `text`, and a `choice` row carries `options`. `locked_by` is the env var name when `source == "env"`.
- `PUT /admin/settings` takes a body `{"<key>": value | null, ...}`. `null` removes the key from `config.local.yaml`.
  - All keys are validated together: range and choice checks, `candidate_k >= top_k` against the resulting values, and `llm_model` pulled.
  - Validation happens before anything is written. On any error it returns **422** `{"detail": {"<key>": "reason"}}` and writes nothing.
  - Unknown, read-only or env-locked keys get 422 too.
  - On success it writes the file atomically (temp file + replace), clears the settings cache, and returns the same shape as GET.

### What changes where

Every reader already calls `get_settings()` per request, except two:
- **The database pool**, created once. It isn't editable, so this is fine.
- **The Ollama client**, which follows `ollama_url`. Also not editable.

`answer.ask` logs `params` from the fresh settings, so `query_log` records what each answer actually used.

## Insights

Endpoints live in `app/admin/insights.py` and are exposed by `app/api/admin.py`.

### `GET /admin/insights?days=7|30|0&tz=Africa/Tunis`

`days=0` means all time. `tz` must be an IANA name that Postgres knows; otherwise it's 400.

```json
{
  "questions": 42, "refused": 5, "invalid": 2, "failed": 1,
  "median_ms": 8600, "max_ms": 56000,
  "per_module": [{"course": "Probability 2", "questions": 20, "refused": 1}],
  "per_day": [{"day": "2026-09-27", "questions": 12, "median_ms": 9100}]
}
```

- **refused:** `answer = NOT_FOUND` (the constant from `app/llm/prompts.py`, passed as a parameter).
- **invalid:** `citation_valid IS false`.
- **failed:** `answer IS NULL`.
- **Medians** use `percentile_cont(0.5)` over non-null `latency_ms`, and are `null` when there's none.
- **`per_module`** groups on `params->>'course'`. A `null` course means "All drawers".
- **`per_day`** groups on `(ts AT TIME ZONE tz)::date`, ascending. Only days with questions are listed; the chart fills the gaps.

### `GET /admin/insights/problems?kind=refused|invalid|slow&days=&limit=50`

Returns rows `{id, ts, question, course, latency_ms}`:
- `refused` and `invalid`: newest first;
- `slow`: `latency_ms` descending.

### `POST /admin/compare` body `{"limit": 20}`

- Takes the most recent `limit` (1–50) distinct `(question, course)` pairs from `query_log`.
- Each question is embedded once, then run through dense and hybrid retrieval with that same vector.
- Returns per question `{question, course, dense: [{chunk_id, title, page, score}], hybrid: [...], verdict_dense, verdict_hybrid, changed}`, plus a summary `{questions, changed, flipped}`.
- It shares the 409 job guard with rescan and re-index, since it's the one slow admin action.
- `app/rag/retrieve.py` gains `retrieve_with_vector(qvec, question, course, mode)`. `retrieve()` becomes a thin wrapper around it that embeds, then calls it. The CLI `app.rag.compare` is rewritten on top of the same function `app/admin/insights.compare(limit)`.

## Frontend

`/admin` gains two sections after Library.

- **Settings:**
  - One catalogue card per group, with a row per key: label, control, help text, and a source tag (`default`, `config.yaml`, `panel`, or `env: LLM_MODEL` with the input disabled).
  - "Reset" appears on rows whose source is `panel`.
  - One "Save changes" button per card, enabled only when something differs from what's loaded.
  - Errors from the 422 response appear under their rows.
  - After saving, the card shows "Saved. The next question uses these settings."
- **Insights:**
  - Period tabs (7 days / 30 days / All), and `tz` from `Intl.DateTimeFormat().resolvedOptions().timeZone`.
  - The numbers as a key-value card, and per module as a small table.
  - **Trend:** an inline SVG: bars for questions per day, and a line for median latency on its own right-hand axis, both labelled. Missing days are drawn as zero-height bars. Colours come from the palette tokens. It follows the dataviz skill when built.
  - **Problems:** three tabs (Refused, Invalid citations, Slowest), with rows linking to `/?open=<id>`.
  - **Compare:** a button with a pending state, then the summary line and a per-question list with changed passages marked `+`/`−`. Only questions whose top 5 changed are expanded.

## Testing

- **`tests/test_settings.py`:**
  - precedence with temp `config.yaml`, `config.local.yaml` and env;
  - GET sources;
  - PUT writes, validates (range, `candidate_k < top_k`, bad keep-alive, unpulled model via a faked tag list), resets with `null`, and refuses env-locked, read-only and unknown keys with nothing written;
  - the cache is cleared, so `get_settings()` reflects the change.
- **`tests/test_insights.py`** (test DB, seeded `query_log`):
  - counts for refused, invalid and failed;
  - medians;
  - `per_module`;
  - `per_day` across a day boundary in `Africa/Tunis` vs UTC;
  - `days` filtering;
  - problems ordering;
  - compare with the fake embedder, both modes and the summary;
  - a bad `tz` gives 400.
- **Frontend:** `npx tsc --noEmit` and `npm run lint`, then the browser pane:
  - change `top_k`, ask a question, and check that `query_log.params` shows the new value;
  - reset;
  - an env-locked row;
  - each insights view;
  - compare.
- **Visual:** one Impeccable pass (desktop and mobile, one fix batch).

## Out of scope

Changing the embedding model or chunking with a full re-index. Editing Blackboard settings (part 3). Authentication.
