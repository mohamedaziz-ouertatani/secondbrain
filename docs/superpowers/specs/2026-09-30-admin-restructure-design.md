# Admin panel restructure: four tabs, a Needs-attention overview, and explanations

Date: 2026-09-30. Status: approved in chat, awaiting spec review.

Today `/admin` is one long page of seven stacked cards (Status, Insights, Evaluation, Library, Tags, Blackboard sync, Settings). Three problems:
- It is too long to scroll: Sync and Settings sit at the bottom.
- Everyday actions (sync, back up, rescan) sit next to rarely used ones (evaluation, tag vocabulary).
- It explains too little: what settings do, what numbers mean, what actions do, and when to use each area.

## Decisions

- `/admin` becomes four pages behind a tab bar: **Overview** (`/admin`), **Library** (`/admin/library`), **Quality** (`/admin/quality`), **Settings** (`/admin/settings`).
- Frontend only. No backend changes, no new endpoints, no new settings.
- The existing cards move; they are not rewritten. The only split is `StatusCard`.
- "Needs attention" is computed in the frontend from four existing endpoints by one pure, unit-tested function.
- Explanations come in three layers: a page intro, an always-visible inline reading, and an optional "How it works" disclosure.
- The visual pass uses the impeccable skill after the restructure works, within the existing DESIGN.md tokens.

## Routes and navigation

- `app/admin/layout.tsx`: the page header ("Admin" plus the current tab's intro line) and the tab bar. Tabs are `<Link>`s with `aria-current="page"` on the active one, so each tab has its own URL and the back button works.
- `app/admin/page.tsx`: Overview.
- `app/admin/library/page.tsx`: `LibraryAdmin` (`#library`), `TagsCard` (`#tags`), `SyncCard` (`#sync`).
- `app/admin/quality/page.tsx`: `InsightsCard` (`#insights`), `EvalCard` (`#eval`).
- `app/admin/settings/page.tsx`: `SettingsCard`.
- The rail's status link stays `/admin`. The rail's "Blackboard: log in needed" link changes from `/admin#sync` to `/admin/library#sync`.
- **Tab badges.** Each tab shows the number of attention items that link into it (none when zero). Items with severity `info` don't count toward badges.
- **Fetching.** A card fetches only while its page is mounted. The layout polls the attention inputs (below) every 10 s while the tab is visible, the same interval `StatusCard` uses today, so badges stay current on every tab.

## Overview page

From top to bottom:

### 1. Needs attention

`lib/attention.ts` exports:

```ts
type Severity = "bad" | "warn" | "info";
type AdminTab = "overview" | "library" | "quality" | "settings";
type AttentionItem = { id: string; severity: Severity; text: string; tab: AdminTab; href: string };
type AttentionInputs = {
  status: AdminStatus | null | "failed";
  library: AdminLibrary | null | "failed";
  sync: SyncStatus | null | "failed";
  insights: InsightsSummary | null | "failed";   // last 7 days
  now: Date;
};
function attention(i: AttentionInputs): AttentionItem[];          // sorted bad → warn → info
function badgeCounts(items: AttentionItem[]): Record<AdminTab, number>;
```

`null` means still loading (no items), and `"failed"` means the request failed. The rules:

| Condition | Severity | Tab › href |
|---|---|---|
| DB down, Ollama unreachable, or the LLM or embedding model not pulled | bad | overview › `/admin#details` |
| `sync.login_needed`, or the most recent finished run is `failed` or `login_required` | bad | library › `/admin/library#sync` |
| `last_full_sync` is null or older than `auto_days` + 2 days | warn | library › `/admin/library#sync` |
| `status.backup` is null or older than 2 days | warn | overview › `/admin#actions` |
| `library.problems.length > 0` (scanned or error files) | warn | library › `/admin/library#library` |
| `library.summary_errors.length > 0` | info | library › `/admin/library#library` |
| Insights with ≥ 10 questions: `invalid / questions > 0.10`, or `refused / questions > 0.25` (one item each) | warn | quality › `/admin/quality#insights` |
| An input is `"failed"` | warn | "Couldn't check ‹the services / the library / the Blackboard sync / recent answers›", linked to that input's page |

Each item's text is one sentence saying what is wrong and why it matters. For example: "3 files couldn't be read, so their pages never appear in answers." When there are no items and every input loaded, the list says "Nothing needs you. Everything is running and up to date."

### 2. Everyday actions (`#actions`)

A strip of four buttons. Each has an explanation line from `adminHelp`:
- **Sync now** calls `POST /admin/sync` with `{ mode: "sync" }`, the same call `SyncCard` makes, and is disabled while a sync is running. It shows a one-line progress state and a link to `/admin/library#sync` for the full log.
- **Back up now** calls `POST /admin/backup`. It moves here from `StatusCard`.
- **Rescan inbox** calls `POST /ingest/rescan`, the same call `LibraryAdmin` makes.
- **Pause / Resume summaries** calls `POST /admin/enrich/pause|resume`. It moves here from `StatusCard`.

### 3. At a glance

Five tiles, each showing its value plus a reading from `readings.ts`: Services, Answer model, Index, Last sync, Last backup.

### 4. System details (`#details`)

This is what remains of `StatusCard`, renamed `SystemDetails`: services, LLM and GPU share, reranker, VRAM, answer times, index, OCR and enrichment progress. Rows keep today's wording and gain an `<Explain>` reading where one exists.

## Explanations

- `lib/adminHelp.ts` holds all the explanation copy: `pageIntro[tab]`, `actionHelp[action]` (`{ line, more }`), `settingMore[key]` (the longer "how it works" text: what it changes, raise vs lower, default), and `metricHelp[metric]` (the definitions of recall@1/5/20, MRR, refusal rate, invalid citations, cited-right-page).
- `lib/readings.ts` holds pure functions that turn a value into a sentence. Each returns `null` when the value is null. Starting set:
  - `recallReading(k, v)`: "the right page is in the top k for N% of questions"
  - `gpuShareReading(share)`: "all on the GPU" when the share is 1, otherwise "part runs on the CPU, so answers are slower"
  - `vramReading(used, total)`: flags ≥ 85% as "nearly full; a larger context window may push the model onto the CPU"
  - `rateReading(n, of, noun)`: "N of M questions (P%)"
  - `backupReading(at, now)` and `syncReading(at, now)`: relative ages, marked as old past the thresholds above
  - `indexReading(index)`: "N files · N passages · N excluded from answers"
- `components/admin/Explain.tsx`: `<Explain line={…} more={…} />` renders the inline line in muted text, plus a `<details><summary>How it works</summary>…</details>` when `more` is given.
- The page intro sits under the tab title in the layout header.
- In Settings, the backend's `help` string stays as the inline line, and `settingMore[key]` adds the disclosure. There is no disclosure when there's no entry.
- In Library, the Rescan, Re-index, Exclude and Include buttons each get an inline line. In Evaluation, each metric column header gets a `metricHelp` disclosure, and the latest run's recall@5 gets a `recallReading`.

## Errors

- A failed input produces a "Couldn't check…" item. It never silently drops items or zeroes out badges.
- If the backend is unreachable (all four inputs failed), the layout header shows the existing "Backend offline" message once, and the attention list is hidden.
- The cards keep their own error handling.

## Design pass

After the restructure works, run the impeccable skill over the tab bar, the attention list, the action strip, the tiles and the `<Explain>` pattern.
- Stay within the DESIGN.md tokens (card catalogue, steel and ground, rule red and blue, module tints). No new visual language.
- Check light and dark mode, visible keyboard focus, and a laptop width of about 1280 px.
- Narrow widths only need to not break: no horizontal scroll, and the tabs wrap.

## Testing

- `npm test` (the node runner), in `lib/attention.test.ts` and `lib/readings.test.ts`:
  - each rule in the table, including the 10-question minimum and the exact thresholds (10% / 25%, 2 days, `auto_days` + 2)
  - `"failed"` inputs producing a "Couldn't check" item
  - `null` inputs producing no items
  - sorting by severity
  - `badgeCounts` per tab, with `info` excluded
  - every reading function with typical values, 0 and null
- In the browser with the dev server:
  - each tab loads with no console errors
  - `/admin/library#sync` scrolls to the sync card
  - badges match the attention list
  - Back up now, Rescan and Pause/Resume still work
  - screenshots of each tab in light and dark mode
- `npm run lint` and `npm run build` pass.

## Out of scope

- Backend changes or new endpoints.
- New settings.
- Changing what `InsightsCard`, `EvalCard`, `TagsCard` or `SyncCard` do. They only gain explanations and move.
- Notifications outside the admin panel. The rail keeps its current Blackboard login prompt.
