# Planner: notes, to-dos and events

Date: 2026-09-29. Status: approved in chat, awaiting spec review.

## Why

Second Brain holds the semester's material but not the semester's time. Quick thoughts, to-dos and deadlines live elsewhere, and Blackboard's own due dates are scattered across course pages. The Planner adds three kinds of item, captured in a second from anywhere in the app, and surfaces what's coming up where you already look: the desk and each drawer.

## Decisions

- **Three kinds of item:**
  - **Notes:** undated thoughts.
  - **To-dos:** a done checkbox and an optional due date.
  - **Events:** a start, with an optional end or all-day. Exams, classes, meetings.
- **Every item has an optional module** (`course`, the same drawer names as the library). NULL means general.
- **Notes stay out of answers by default.** "File into drawer" writes a note to `inbox/<module>/<title>.md`, where the existing watcher indexes it and answers can cite it.
- **Blackboard deadlines are imported as to-dos** during every sync. A read-only probe on 2026-09-29 found that Blackboard's calendar holds only gradebook due dates: 23 this semester, across CSR, SDG, DEVOPS and Optimization for ML. It holds no exams and no class times, so those are typed by hand.
- **Capture:**
  - a capture box on the Planner page;
  - a global popup (`N` outside text fields, `Alt+N` anywhere);
  - one-line parsing, done in code with `dateparser`, never by the LLM. You always see the reading and confirm it before saving.
- **Reminders are in the app only:** a Coming-up strip on the desk and in each drawer, the Planner calendar, and a rail badge. No notifications and no feeds.
- **Storage is Postgres,** in the existing backend. This was chosen over Markdown files with front-matter (date queries and the Blackboard upsert become file bookkeeping) and over a CalDAV server (a new service, and notes don't fit CalDAV).
- **The calendar is hand-built** (agenda plus month grid) in the DESIGN.md language, rather than FullCalendar.

## Data (migration `007_planner.sql`)

```sql
CREATE TABLE planner_items (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('note', 'todo', 'event')),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',        -- markdown: the note text, or details on a to-do/event
    course      TEXT,                            -- module (drawer); NULL = general
    starts_at   TIMESTAMPTZ,                     -- event start, or to-do due date
    ends_at     TIMESTAMPTZ,                     -- events only, optional
    all_day     BOOLEAN NOT NULL DEFAULT false,
    done_at     TIMESTAMPTZ,                     -- to-dos only; NULL = open
    source      TEXT NOT NULL DEFAULT 'me' CHECK (source IN ('me', 'blackboard')),
    source_id   TEXT,                            -- Blackboard calendar item id
    removed_at  TIMESTAMPTZ,                     -- Blackboard item no longer returned by Blackboard
    filed_path  TEXT,                            -- inbox-relative path once a note is filed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id),
    CHECK (kind = 'note' OR title <> ''),
    CHECK (kind <> 'note' OR (starts_at IS NULL AND done_at IS NULL)),
    CHECK (kind = 'event' OR ends_at IS NULL),
    CHECK (kind <> 'event' OR starts_at IS NOT NULL),
    CHECK (ends_at IS NULL OR ends_at >= starts_at)
);
CREATE INDEX planner_items_when_idx ON planner_items (starts_at) WHERE starts_at IS NOT NULL;
CREATE INDEX planner_items_course_idx ON planner_items (course);
```

**Dates and times:**
- `starts_at` is both the event start and the to-do due date, so the calendar and Coming-up run one range query.
- Times are stored in UTC and shown in the browser's local time.
- An all-day item is stored at local midnight of its day, with `all_day = true`. The local time zone comes from the request: the frontend sends `tz` (an IANA name) to `/planner/parse`.

**Blackboard rows:**
- Title, `starts_at` and `course` are overwritten on each sync.
- `body` is set only on first import. `done_at` and `body` belong to you.
- An item inside the fetched window that Blackboard no longer returns gets `removed_at`. It isn't deleted, and `removed_at` is cleared if the item comes back.

**Filed notes:**
- Once `filed_path` is set, the file is the source of truth. Editing the note in the Planner rewrites the file atomically, and the watcher re-indexes it.
- If the file is gone from disk, `filed_path` is cleared when the item is next read, and the note keeps its last text.
- A filed note can't change module. Move the file on disk instead.

**Deletes and backups:**
- A delete is hard. The UI gives 5 seconds to undo first, like History.
- `planner_items` joins `TABLES` in `app/admin/backup.py` (primary key `id`, no JSONB columns), because your notes can't be regenerated.

## Backend: `app/planner/`

| File | Job |
|---|---|
| `store.py` | CRUD, range query, upcoming query, search. Plain SQL, like `rag/history.py` |
| `parse.py` | One line → draft item. Pure function taking `text`, `course`, `now`, `tz` and the known modules; no database |
| `blackboard.py` | Blackboard calendar items → rows; upsert and removed detection |
| `file.py` | File a note into `inbox/`; rewrite a filed note; clear a missing `filed_path` |
| `app/api/planner.py` | `APIRouter(prefix="/planner")`, included in `main.py` |

### Routes

| Route | Does |
|---|---|
| `GET /planner/items?kind=&course=&from=&to=&q=&open=` | List. `from`/`to` filter `starts_at` (calendar). `q` does a case-insensitive `ILIKE` on title and body. `open=1` hides done to-dos. Sorted by `starts_at` then `created_at DESC`; undated items come last |
| `GET /planner/upcoming?course=&days=7` | Open to-dos due before now (overdue), plus to-dos and events with `starts_at` from now to now + `days`. Excludes done items and `removed_at` items |
| `POST /planner/items` | Create; returns the item |
| `PATCH /planner/items/{id}` | Partial update, including `done: true/false` (sets or clears `done_at`). On `source = 'blackboard'`, changing `title`, `starts_at` or `course` returns 409 |
| `DELETE /planner/items/{id}` | 204 |
| `POST /planner/parse` `{text, course?, tz}` | Draft `{kind, title, course, starts_at, ends_at, all_day, matched: [{start, end, role}]}`. Saves nothing |
| `POST /planner/items/{id}/file` | Notes only. Needs a `course` (400 if missing). Writes the `.md` and returns the item with `filed_path` |

The frontend's module list comes from the existing `/courses`. The parser reads known modules from the inbox folders, as the sync does.

**Errors:**
- A CHECK violation becomes a 422 with a readable message, e.g. "an event needs a start" or "a note has no date".
- An unknown id gives 404.

### Parsing (`parse.py`)

`dateparser` is added to the backend dependencies. It works offline.

1. **Module:** the longest case- and accent-insensitive match of a known module name, or of an alias from a small built-in map ("devops", "proba", "proba 2", "optim", "deep learning", "big data", "aws", "blockchain", "csr", "sdg"). The aliases can be extended with `planner_aliases` in `config.yaml`. With no match, the `course` passed in (the open drawer) is used.
2. **Kind:**
   - Event words → event: `exam`, `examen`, `DS`, `test`, `cours`, `class`, `lecture`, `réunion`, `meeting`, `soutenance`.
   - Due words → to-do: `due`, `deadline`, `rendre`, `rendu`, `pour le`, `avant`, `before`, `by`, `TP`, `todo`, `à faire`.
   - A date with no kind word → to-do. No date → note. A leading `note:` or `idea:` forces a note.
3. **Date and time:** `dateparser.search.search_dates`, with `languages=['fr','en']`, `PREFER_DATES_FROM='future'`, `RELATIVE_BASE=now` and the request's `tz`.
   - A lone time (`9h`, `14:30`, `23h59`) sets the time on the found date.
   - A range (`9h-11h`, `9h à 11h`) sets `ends_at` on events.
   - A to-do with a date but no time is due at 23:59 local.
   - An event with a date but no time is all-day.
   - Numeric dates are day-first (`12/01` = 12 January).
4. **Title:** the text with the module, date and time spans removed, and whitespace collapsed. Kind words stay, because "DEVOPS TP" reads better than "DEVOPS". If nothing is left, the original text is used.
5. **`matched`:** the character spans and their roles (`course`, `date`, `time`, `kind`), so the UI can underline them.

Arabic is out of scope unless adding `'ar'` passes the test table without breaking any French or English case.

## Blackboard import

**Hook:** a new step at the end of `run()` in `app/sync/blackboard.py`, after the files. It runs on a real sync and on `--dry-run`, but not on `--probe`. The logic lives in `app/planner/blackboard.py`; the sync module only calls it and emits the result.

1. **Fetch** `GET /learn/api/public/v1/calendars/items?since=&until=` from today − 30 days to today + 180 days, in windows of at most 12 weeks.
2. **Map to modules:** keep only items whose `calendarId` is the id of a course in `run()`'s course → folder `mapping` with a folder (unmapped courses are skipped, the same rule as files). `--course X` limits it to that module.
3. **Upsert** on `(source = 'blackboard', source_id = item.id)`:
   - `kind = 'todo'`, `title = item.title`, `starts_at = item.end` (the due time), `course = folder`;
   - `body = item.description` (HTML converted with `markdownify`) on insert only;
   - clear `removed_at`.
4. **Removed:** rows with `source = 'blackboard'`, `starts_at` inside the fetched window, a course that was fetched, and a `source_id` not returned get `removed_at = now()`, if it isn't already set.
5. **Emit** `{"type": "deadlines", "new": n, "updated": n, "removed": n}`. On dry-run, emit `{"type": "deadlines", "would_import": n}` and write nothing. The admin Sync card's run log shows the line.

**Failure:**
- Any error in the step emits `{"type": "deadlines", "failed": "<message>"}`, and the sync's exit code is unchanged.
- The step writes to Postgres through `app.db`, so CLI and admin syncs behave the same. If the database is unreachable from a CLI run, the step reports as failed.

## Frontend

**Rail:**
- A fourth view, **Planner** (Lucide `CalendarDays`), after History. It respects the open drawer through `drawerHref`.
- The view carries a `rule-red` count badge: overdue plus due-today open to-dos, plus events today, in the current drawer scope. It's hidden at 0.

**Planner page** (`app/planner/page.tsx`):
- **Capture card.** It uses the `CaptureLine` component: a working-card line with the red caret.
  - While typing, it calls `/planner/parse` with a 250 ms debounce and shows the reading as a call-number line (e.g. `TO-DO · DEVOPS · due Fri 3 Oct 23:59`), with the matched spans underlined.
  - Each part of the reading can be clicked to override it: a kind toggle, a module select and date/time inputs.
  - Enter saves.
  - A parse failure or timeout falls back to saving a note with the text as its title.
- **Calendar card.** **Agenda** (the default) and **Month** toggles, and the choice is remembered in `localStorage`.
  - Agenda: grouped by day from today onward, with an **Overdue** group pinned first in `bad`.
  - Month: a day grid, with items as chips that have a drawer-tint left edge. Clicking a day scrolls the agenda to it.
  - Done to-dos are struck and muted. Removed Blackboard items are struck and labelled "removed on Blackboard".
- **Notes & to-dos card.** Tabs **To-dos** (open, then done, collapsible) and **Notes** (newest first), with search (`q`) and a checkbox on each to-do row.

**Item panel:**
- A card sliding over the right side, like the reader. It holds the title, kind, module, date fields and the body. The body is edited as Markdown, with a preview through `Prose`.
- It saves each field on blur, with no Save button.
- On Blackboard items, title, date and module are read-only, with a `FROM BLACKBOARD` call-number.
- On notes, **File into drawer** is shown; it's disabled until a module is set. Once filed, it shows "Filed · open in reader", linking to the document.
- **Delete** gives 5 seconds to undo, using `UndoNote`.

**Global capture popup** (`components/CaptureDialog.tsx`, mounted in `app/layout.tsx`):
- It opens on `N` when focus isn't in an input, textarea, select or contenteditable, or on `Alt+N` anywhere.
- It uses the same `CaptureLine`, pre-filled with the open drawer.
- Enter saves, closes and shows "Saved · view". Esc closes it.
- Focus is trapped while it's open and returned afterwards.

**Coming-up strip** (`components/ComingUp.tsx`):
- It shows overdue items plus the next 7 days from `/planner/upcoming`, at most 5 rows plus "N more → Planner".
- It sits on the desk (`/`) above the recent-questions stack, and on the drawer page scoped to the module, above the catalogue.
- It's hidden when empty.
- Ticking a to-do there marks it done.

## Testing

Backend, with pytest and the existing `env` fixture:
- `test_planner_parse.py`: a table of about 30 French and English one-liners with a fixed `now` and `tz = Africa/Tunis`. It asserts kind, course, `starts_at`, `ends_at` and `all_day`. No database.
- `test_planner_store.py`: CHECK rules, the range query, `upcoming` (overdue, window, done and removed excluded) and search.
- `test_planner_api.py`: routes, the 409 on Blackboard fields, the 422 messages, File into drawer (writes the file, a name clash gets ` (2)`, an edit rewrites the file, a missing file clears `filed_path`).
- `test_planner_blackboard.py`: with `fake_sync`. It covers first import, a re-sync that updates title and date but keeps `done_at` and `body`, `removed_at` set and then cleared on return, unmapped courses skipped, a failure that leaves the sync's exit code unchanged, and dry-run writing nothing.
- `test_backup.py`: `planner_items` goes through a backup and restore.

Frontend: there is no test runner, and none is added. It's checked in the browser pane against the dev server:
- capture and its reading, `N` and `Alt+N`;
- Agenda and Month;
- ticking a to-do;
- filing a note and opening it in the reader;
- Coming-up on the desk and in a drawer;
- the rail badge;
- dark mode.

## Stages

Built on the `planner` branch. Each stage ends with its tests passing and a commit.
1. **Backend core:** migration, `store`, `parse`, routes, backup.
2. **Blackboard import:** the sync step and the Sync card's run log line.
3. **Planner UI:** page, `CaptureLine`, item panel, File into drawer.
4. **Everywhere else:** global popup, Coming-up on the desk and in drawers, the rail badge, a README section.

## Out of scope

- Recurring events. This can be added later as a `repeat_weekly_until` column.
- Notifications of any kind (browser, Windows toast).
- An `.ics` feed or import.
- LLM-based parsing.
- Arabic parsing, unless it passes the tests (see Parsing).
- Two-way sync to Blackboard. Ticking an imported to-do never touches Blackboard.
