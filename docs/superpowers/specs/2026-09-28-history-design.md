# Server-side history with delete

Date: 2026-09-28. Status: approved in chat, awaiting spec review.

## Problem

Past answers live only in the browser (`localStorage["sb.history.v1"]`, [page.tsx](../../../frontend/app/page.tsx)):
capped at 40, shown only for the current drawer, and separate per origin (ports 3000 and 3001 do not share it).
There is no way to delete one. Meanwhile every question is already stored server-side in `query_log`,
with its answer and full citations.

## Decisions

- History is read from `query_log`. No new table, no migration.
- Delete is **permanent**: the row is removed from `query_log`, so it also leaves any future evaluation set.
- Old messages are browsed on a new **History page**. The desk keeps its short "Earlier in this drawer" stack.
- Only **single delete**, with a 5 s undo instead of a confirm dialog. No multi-select, no "clear all".
- Each message stays one question and its answer. No threads or conversations.

## Backend (`backend/app/api/routes.py`, logic in `backend/app/rag/history.py`)

A message is `{id, ts, question, course, answer, citations, citation_valid, latency_ms}`, where
`course = params->>'course'`. Refusals are ordinary messages, and a row whose answer is NULL (a
stream that failed before any text arrived) is returned with `answer: null`.

| Route | Behaviour |
|---|---|
| `GET /history?course=&q=&before=&limit=` | Newest first by `id`. `course` filters exactly. `q` is a case-insensitive substring match on question or answer (ILIKE, with `%` and `_` escaped). `before=<id>` returns rows with `id < before`. `limit` defaults to 50 and is clamped to 1..200. |
| `GET /history/{id}` | One message; 404 if absent. |
| `DELETE /history/{id}` | Deletes the row; 204, or 404 if absent. |

## Frontend

- `lib/api.ts`: `HistoryItem` type, `fetchHistory`, `fetchHistoryItem`, `deleteHistory` (keepalive).
  Also a mapper from `HistoryItem` to the desk's `Entry` (`id = String(row.id)`, `logId = row.id`,
  `startedAt = ts - latency_ms`, `endedAt = ts`).
- `Entry` gains `logId?: number`, set from `done.log_id` for answers asked in this session.
- **Desk (`/`)**:
  - Loads the 40 most recent messages from `GET /history?limit=40` and removes `sb.history.v1`.
  - `/?open=<id>` makes that message active, fetching it with `GET /history/{id}` if it is not already loaded.
  - The open answer and each past card get a delete control.
- **History page (`/history`)**:
  - Linked from the rail next to Documents, following the current drawer like Documents does.
  - Rows are grouped by day (Today, Yesterday, then `12 Sep`). Each row shows the question, the drawer
    tint and code, the first line of the answer, and the time.
  - Search input (debounced) and "Load more" (keyset on `before`).
  - Clicking a row goes to `/?open=<id>` (keeping the drawer).
  - Styled in the card catalogue world, per `DESIGN.md` and `.impeccable/`.
- **Delete with undo** (shared hook, used by desk and History):
  - The message is hidden at once and an "Answer deleted · Undo" note shows for 5 s.
  - The `DELETE` is sent when the 5 s end, or on `pagehide`/unmount, using `keepalive`.
  - Undo within the window sends nothing.
  - If the request fails, the message is restored with an error note.
  - A message still streaming cannot be deleted: there is no `logId` yet.

## Testing

- Backend integration tests in the style of `tests/test_pipeline.py` (a throwaway `secondbrain_test` DB,
  skipped if Postgres is unreachable): ordering, `before` paging, course filter, search (including a
  literal `%`), limit clamping, get-one and 404, delete and 404.
- Frontend: `npx tsc --noEmit` and `npm run lint` clean. Then a check in the browser pane: list,
  filter, search, load more, reopen on the desk, delete, undo, and delete from the desk.

## Out of scope

Multi-select delete, clear drawer/all, soft delete, conversation threads, editing messages.
