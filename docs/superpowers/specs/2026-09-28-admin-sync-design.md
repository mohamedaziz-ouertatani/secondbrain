# Admin panel, part 3: Blackboard sync from the browser

Date: 2026-09-28. Status: approved in chat, awaiting spec review.

Parts 1 (Status + Library) and 2 (Settings + Insights) are shipped. This is the last admin sub-project.

## Decisions

- The panel runs the **existing sync script as a subprocess** (`python -m app.sync.blackboard`). It never runs in the backend's own process: a Playwright crash can't take down the API, and only one process uses the Edge profile at a time.
- The script gains a **`--json` flag** that prints one event per line. Without it, the text output is unchanged.
- **Actions:** Sync now, Sync one module, Preview (dry run), Course mapping (probe), Log in, Cancel. One job at a time.
- A **weekly automatic headless sync** is run by the backend. It is controlled by a new setting `sync_auto_days` (default 7; 0 turns it off), editable in the panel.
- An expired session is surfaced, not retried. The panel and the rail footer say "log in needed" until a login or a successful run clears it.

## The script (`app/sync/blackboard.py`)

### Events

`run()` gains `emit: Callable[[dict], None] = print_event` and sends dicts instead of printing:

| type | fields | text printed by `print_event` (unchanged from today) |
|---|---|---|
| `courses` | `courses: [{name, folder}]` (folder null when skipped), `probe: bool` | the "N courses on Blackboard" block; with `probe`, also the "Probe only" line |
| `course` | `folder, files, to_download, unchanged, deleted_locally, skipped: {ext: n}` | the "`folder`: N readable files…" line and the "skipped, not readable yet" line |
| `file` | `folder, path, action, kb?, error?, adopt?` where `action` is `downloaded`, `saved_page`, `already_had`, `would_download`, `would_save_page` or `failed` | the matching per-file line |
| `done` | `mode` (`sync`, `preview` or `probe`), `files, bytes` | the "Done: …" line (sync mode only) |

`main()` sends these as well:

| type | when |
|---|---|
| `login_waiting` | a visible window opened and it's waiting for the user (replaces the "Log in to Blackboard…" print) |
| `logged_in` | the login succeeded |
| `login_required` | headless and the session expired; exits with **code 3** |
| `error` `{message}` | any other fatal error; exits with code 1 |

`--json` swaps `print_event` for `json_event`, which writes `json.dumps(event, ensure_ascii=False)` plus a newline and flushes. Existing tests that check the text output must still pass unchanged.

## Backend

### Job runner (`app/admin/sync.py`)

- `SyncRunner(command: list[str] | None = None, runs_file: Path = DATA_DIR / "sync-runs.json", clock=time.time)` has one module-level instance. `command` defaults to `[sys.executable, "-m", "app.sync.blackboard"]` with cwd `backend/` and `PYTHONUTF8=1`. Tests inject a fake script.
- `start(mode, course=None)`:
  - `mode` is one of `sync`, `preview`, `probe` or `login`.
  - Flags: `sync` passes `--headless`, `preview` passes `--headless --dry-run`, `probe` passes `--headless --probe`, and `login` passes `--probe` with **no** `--headless`, so a window opens.
  - `course` adds `--course`.
  - It raises `Busy` if a job is running. A reader thread parses stdout lines. A line that isn't JSON becomes `{type: "log", text}`.
- The job state holds `{id, mode, course, started_at, finished_at, state, exit_code, counts: {downloaded, saved_page, already_had, would_download, would_save_page, failed}, events (the last 200), courses (from the courses event)}`. `state` is one of `running`, `ok`, `login_required`, `failed` or `cancelled`.
- `cancel()` terminates the process, and after 5 s kills it. The run is recorded as `cancelled`.
- **When a run ends**, a summary without events is added to the runs file (the last 20 runs, written atomically).
  - `login_needed` is set when the exit code is 3.
  - It's cleared by an `ok` run in any mode, including `login`.
- `last_full_sync()` is the latest of:
  - the end time of the last `ok` run with mode `sync` and no course;
  - the modification time of `blackboard-sync.json`, which the command-line sync writes too.
- `due(now) -> bool` (pure, tested with an injected clock) is true when:
  - `sync_auto_days > 0`,
  - no job is running,
  - `login_needed` is not set, and
  - `now - last_full_sync() >= sync_auto_days` days (never synced counts as due).

### Scheduler

The app lifespan starts a daemon thread. It checks `due()` every 60 minutes, with the first check 5 minutes after startup so it doesn't compete with the startup rescan, and starts a `sync` run when due. The lifespan stops it on shutdown.

### Settings

`Settings.sync_auto_days: int = 7`. `admin/settings.py` gains a **"Blackboard"** group with one editable row: `sync_auto_days`, an `int` from 0 to 30, with help text "Days between automatic syncs; 0 turns them off". The existing tests expect exactly two groups (`["Retrieval", "Answers"]`); update them to three.

### API (`app/api/admin.py`)

| Route | Behaviour |
|---|---|
| `GET /admin/sync` | `{job: <state or null>, runs: [...], login_needed, last_full_sync, next_auto (ISO or null when off, running or blocked), auto_days, modules: [inbox folder names]}` |
| `POST /admin/sync` `{mode, course?}` | 202 with the job, or **409** if one is running. `mode` is `sync`, `preview` or `probe` (login has its own route). A `course` that isn't an inbox folder gets 400. |
| `POST /admin/sync/login` | Starts a `login` job (202 or 409). |
| `POST /admin/sync/cancel` | 200 with the job, or 404 if nothing is running. |

`GET /health` gains `blackboard_login_needed: bool` (read from the runs file), so the rail can show it without another request.

## Frontend

- **`components/admin/SyncCard.tsx`**, placed between Library and Settings on `/admin`.
  - **Header line:** "Last full sync 3 days ago · 12 files", then "Next automatic sync in 4 days" (or "Automatic sync off"). When `login_needed`, a notice reads "Your Blackboard session expired. Log in to sync again." with a **Log in** button. The Log in button explains that an Edge window will open.
  - **Actions:** Sync now, Preview, Course mapping, then a module `<select>` with "Sync this module". All are disabled while a job runs.
  - **While running:** the page polls `GET /admin/sync` every 1.5 s. It shows counts (downloaded, pages saved, failed), and a live list of `file` events grouped by folder: newest first, capped at 200, failed ones in `--bad` with their error. There's a **Cancel** button.
  - **When a run ends:** a summary line, for example "Done: 3 files, 1.2 MB", "Preview: 5 files would be downloaded", "Session expired: log in", "Cancelled" or "Failed: <message>".
  - **Course mapping:** a table of Blackboard course → inbox folder, with skipped courses muted and the note "Fix wrong matches with blackboard_course_map in config.yaml."
  - **Recent runs:** a `<details>` list of the last runs (mode, when, outcome, files).
- **Rail:** when `/health` reports `blackboard_login_needed`, the footer shows a second line, "Blackboard: log in needed", which links to `/admin#sync`.

## Testing

- **`tests/test_blackboard.py`:** the existing tests keep passing, since the text output is unchanged. New tests:
  - `run(emit=list.append)` with the `FakeAPI` yields `courses`, `course`, `file` and `done` events with the right actions for sync, preview and probe;
  - `json_event` writes one parseable line per event;
  - headless `main()` with an expired session sends `login_required` and exits 3 (with `PlaywrightAPI` faked).
- **`tests/test_sync_runner.py`:** a fake script (`tests/fake_sync.py`) prints canned JSON lines according to its argv, and can sleep or exit 3. It covers:
  - start → events and counts → `ok`, recorded in the runs file;
  - 409 (`Busy`) while running;
  - cancel → `cancelled`;
  - exit 3 → `login_required` and `login_needed` set, which a later `ok` run clears;
  - a non-JSON line becomes a `log` event;
  - `due()` with an injected clock: never synced, recent, overdue, turned off, login needed, and a running job;
  - `last_full_sync()` honouring the state file's modification time;
  - the routes, including the 400 for an unknown course.
- **Browser** (real Blackboard, only with the user's go-ahead): Course mapping, Preview, and Sync one module on a small module. A full Sync now and Log in are left to the user to trigger.
- **Visual:** one Impeccable pass (desktop and mobile, one fix batch).

## Out of scope

Editing `blackboard_course_map` from the panel, per-course schedules, notifications outside the app, and deleting local files that were removed on Blackboard (still never done).
