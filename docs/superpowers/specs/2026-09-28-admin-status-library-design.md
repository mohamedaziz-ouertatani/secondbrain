# Admin panel, part 1: Status + Library

Date: 2026-09-28. Status: approved in chat, awaiting spec review.

The admin panel is built as three sub-projects on one `/admin` page:
1. Status + Library (this spec).
2. Settings and retrieval: editable settings, query-log analytics, the dense vs hybrid comparison.
3. Blackboard sync from the browser.

## Decisions

- `/admin` is one page. It is reached by clicking the rail footer's status line ("Ready · qwen3:4b-instruct"), which becomes a link. The three top views are unchanged.
- There is no authentication: the backend listens on 127.0.0.1 and there is one user.
- "Remove" means **exclude**: the file stays on disk, its path is stored in a new `excluded_paths` table, and it leaves the index. Ingestion skips it until it is included again.
- Deleting or renaming a whole module folder now updates the index (a watcher gap found earlier today).

## Backend

### Migration `004_excluded_paths.sql`

```sql
CREATE TABLE excluded_paths (
    path        TEXT PRIMARY KEY,           -- inbox-relative, same form as documents.path
    excluded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Pipeline (`app/ingest/pipeline.py`)

- `ingest_file(path, embedder, counter, force=False)`:
  - Returns `"excluded"` without touching the index when the path is in `excluded_paths`.
  - With `force=True`, it re-ingests even when the hash and parser version are unchanged.
- `rescan()` counts excluded files under `"excluded"`. They are not added to `seen`, so a stale document row for them is removed like a vanished file.
- `exclude(rel) -> bool`: inserts into `excluded_paths` (idempotent) and deletes the document (chunks cascade). Returns whether a document was removed.
- `include(rel) -> str`: deletes the `excluded_paths` row and, if the file exists and is supported, returns `ingest_file(...)`. Otherwise it returns `"missing"`.
- `reindex(rel=None, course=None) -> dict[str, int]`: runs `ingest_file(force=True)` over one file, or over every file on disk under `inbox/<course>/`. It returns status counts.
- `remove_folder(path) -> int`: deletes documents whose path starts with `<rel>/`. Returns how many were removed.
- All writes keep using the module's single `_lock`.

### Watcher (`app/ingest/watcher.py`)

Directory events are no longer ignored:
- `deleted` directory: `remove_folder(src)`.
- `moved` directory: `remove_folder(src)`, then `touch` every supported file under `dest`, so it is re-ingested under its new course.
- `created` directory: `touch` every supported file under it. (A folder pasted in one go can arrive as a single directory event on Windows.)

### Status (`app/admin/status.py`, route `GET /admin/status`)

```json
{
  "services": {"db": {"ok": true}, "ollama": { ...ollama.status()... }},
  "llm": {"loaded": true, "model": "qwen3:4b-instruct", "gpu_share": 0.67, "expires_at": "2026-09-28T10:30:00Z"},
  "gpu": {"available": true, "name": "NVIDIA GeForce RTX 2050", "used_mib": 3712, "total_mib": 4096},
  "answers": {"count": 20, "median_ms": 8100, "max_ms": 56000, "last_at": "2026-09-28T08:43:00Z"},
  "index": {"documents": 81, "chunks": 521, "excluded": 0, "db_bytes": 48234496}
}
```

- **`llm`** comes from Ollama's `/api/ps`:
  - `gpu_share = size_vram / size` for the entry whose name is the configured LLM.
  - `{"loaded": false}` when that model isn't listed, and `null` when Ollama is unreachable.
- **`gpu`** comes from `nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits` with a 3 s timeout. If the binary is missing, the call fails or the output can't be parsed, it is `{"available": false}`.
- **`answers`** covers the last 20 `query_log` rows whose `latency_ms` is not null. `median_ms`, `max_ms` and `last_at` are `null` when there are none.
- **`index.db_bytes`** is `pg_database_size(current_database())`.
- Each part is computed independently. A failing part becomes `null` (or `available: false`) and never fails the whole response.

### Library routes (`app/api/admin.py`, an `APIRouter` with prefix `/admin`)

| Route | Behaviour |
|---|---|
| `GET /admin/library` | `{"modules": [{"course", "documents", "chunks", "problems"}], "problems": [{"id", "path", "title", "course", "status", "error"}], "excluded": [{"path", "excluded_at", "on_disk"}]}`. Modules are sorted by name; `course` null is listed as it is. |
| `POST /admin/reindex` body `{"path": str}` or `{"course": str}` | Forced re-index. Returns status counts. 400 if neither or both are given; 404 if the path isn't a supported file inside the inbox. Shares the 409 guard with `/ingest/rescan`. |
| `POST /admin/exclude` body `{"path": str}` | Excludes. 200 `{"removed": bool}`. |
| `POST /admin/include` body `{"path": str}` | Includes. 200 `{"status": str}`. 404 if the path was not excluded. |

- Paths are inbox-relative and resolved against the inbox. A path that escapes the inbox is refused with 400.
- The existing rescan lock becomes shared: `_rescan_lock` moves from `routes.py` into a small module both routers import.
- `GET /documents` stays as it is. Excluded files have no document row, so the Drawer stops listing them without any change.

## Frontend

- **`app/admin/page.tsx`** has two sections, **Status** and **Library**, in the card catalogue world (`DESIGN.md`).
  - Status polls `GET /admin/status` every 10 s while the tab is visible (checked via `document.visibilityState`).
  - Library loads `GET /admin/library`, and reloads after every action.
- **Status** shows one catalogue card of key–value rows: Services, LLM, GPU, Answers, Index.
  - The GPU row has a VRAM meter: a plain bar, `used / total`.
  - When a service is down, its row names the problem and the fix, reusing the rail's HealthLine wording.
- **Library** has:
  - a module table (documents, chunks, problem count, a "Re-index" action per module);
  - a problem-file list (title, call number, reason, "Re-index" and "Exclude");
  - an excluded list (path, date, whether it's still on disk, "Include");
  - "Rescan inbox" at the top.
  - Every action shows a pending state, then the result counts or an error inline.
- **Rail:** the footer's status line becomes a link to `/admin`, with `aria-current` when on `/admin`.
- `lib/api.ts` gets the types and a small `postJSON` helper.

## Testing

- **Backend integration tests** (throwaway `secondbrain_test` DB, fake embedder, `tmp_path` inbox):
  - exclude removes the document, and a later `ingest_file` returns `"excluded"`;
  - `rescan` skips excluded files and drops a stale row;
  - include re-ingests;
  - a forced re-index re-embeds an unchanged file;
  - `reindex(course=...)` covers only that module;
  - `remove_folder` drops only that prefix;
  - a path escaping the inbox gets 400.
- **Status unit tests** with Ollama and `nvidia-smi` faked: normal output, the model not loaded, `nvidia-smi` missing, and an empty `query_log`.
- **Watcher:** a test that calls the handler with directory `deleted` and `moved` events against a real temp inbox and asserts the index result. No real filesystem watching.
- **Frontend:** `npx tsc --noEmit` and `npm run lint` clean. Then a check in the browser pane: status values against `nvidia-smi` and `ollama ps`, exclude/include and re-index on a test file in a throwaway module folder, and deleting that folder.
- **Visual pass** with Impeccable against `DESIGN.md`.

## Out of scope

Editing settings, query-log analytics and the retrieval comparison (part 2). Running the Blackboard sync (part 3). Authentication.
