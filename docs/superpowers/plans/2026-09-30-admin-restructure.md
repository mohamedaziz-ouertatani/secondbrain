# Admin Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `/admin` into four tabbed pages (Overview, Library, Quality, Settings), add a Needs-attention overview with everyday actions, and explain every setting, number and action.

**Architecture:** A client layout at `app/admin/layout.tsx` wraps the four pages in an `AdminDataProvider`. It polls four existing endpoints every 10 s and computes attention items with a pure function (`lib/attention.ts`). Pure reading functions (`lib/readings.ts`) turn numbers into sentences. All explanation text lives in `lib/adminHelp.ts` and is shown through one `<Explain>` component. The existing cards move to the new pages mostly unchanged; `StatusCard` is split into an action strip, glance tiles and a system-details card.

**Tech Stack:** Next.js 16.3 (App Router; read `frontend/node_modules/next/dist/docs/` before using an unfamiliar API), React 19, TypeScript, plain CSS in `app/globals.css`, and node's own test runner (`npm test`).

**Spec:** `docs/superpowers/specs/2026-09-30-admin-restructure-design.md`

## Global Constraints

- Frontend only. No backend changes, no new endpoints, no new settings.
- Work on a branch named `admin-tabs` in the **main checkout** (`C:\dev\Second Brain`), **not** in a git worktree: a backend started from a worktree against the shared DB rescans an empty inbox and deletes every document.
- Pure logic in `lib/*.ts` must import other `lib` files with a `.ts` extension, and must use `import type` for anything from `./api.ts`: node's `--experimental-strip-types` runner can't resolve `lib/api.ts`'s extensionless imports at runtime. Components import with the `@/lib/...` alias, as they do today.
- Attention thresholds: invalid citations > 10% or refusals > 25% of answers, over the last 7 days, only when there are ≥ 10 questions. Backup old after 2 days. Sync old after `auto_days` + 2 days.
- Severity `info` items appear in the list but don't count toward tab badges.
- Visual work uses only the existing tokens in `app/globals.css` `:root` (`--card`, `--card-2`, `--ink`, `--muted`, `--rule-red`, `--rule-blue`, `--steel*`, `--primary`, `--bad`, `--good`, `--sel`, `--focus`). No new colours.
- Copy style: plain sentences, no em dashes, "·" as the separator in compact lines, and a British spelling ("summarised").
- Commit messages follow the repo's style (a sentence, no `feat:` prefix) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Status | Responsibility |
|---|---|---|
| `frontend/lib/readings.ts` | create | Pure number-to-sentence functions, ages, old checks, the services line and the counts line |
| `frontend/lib/readings.test.ts` | create | Tests for `readings.ts` |
| `frontend/lib/attention.ts` | create | `attention()` rules and `badgeCounts()` |
| `frontend/lib/attention.test.ts` | create | Tests for `attention.ts` |
| `frontend/lib/adminHelp.ts` | create | All explanation copy: page intros, settings, actions, metrics, system details |
| `frontend/components/admin/Explain.tsx` | create | Inline reading plus an optional "How it works" disclosure |
| `frontend/components/admin/AdminData.tsx` | create | Provider: polls the 4 endpoints, exposes slots, items, badges, `now` and `refresh` |
| `frontend/app/admin/layout.tsx` | create | Header, intro, tab bar with badges, offline notice |
| `frontend/app/admin/page.tsx` | rewrite | Overview |
| `frontend/app/admin/library/page.tsx` | create | LibraryAdmin, TagsCard, SyncCard |
| `frontend/app/admin/quality/page.tsx` | create | InsightsCard, EvalCard |
| `frontend/app/admin/settings/page.tsx` | create | SettingsCard |
| `frontend/components/admin/NeedsAttention.tsx` | create | The attention list |
| `frontend/components/admin/ActionStrip.tsx` | create | Sync now, Back up now, Rescan inbox, Pause/Resume summaries |
| `frontend/components/admin/GlanceTiles.tsx` | create | Five tiles |
| `frontend/components/admin/SystemDetails.tsx` | create | What remains of StatusCard, reading from the provider |
| `frontend/components/admin/StatusCard.tsx` | delete | Replaced by the three components above |
| `frontend/components/admin/{LibraryAdmin,TagsCard,SyncCard,InsightsCard,EvalCard,SettingsCard}.tsx` | modify | Section ids and explanations |
| `frontend/components/Rail.tsx` | modify | The login link goes to `/admin/library#sync` |
| `frontend/app/globals.css` | modify | Styles for the tabs, badges, attention list, actions, tiles and explain |
| `README.md` | modify | The Admin panel section |

---

### Task 1: Readings

**Files:**
- Create: `frontend/lib/readings.ts`
- Test: `frontend/lib/readings.test.ts`

**Interfaces:**
- Consumes: the `AdminStatus` type from `frontend/lib/api.ts` (type-only).
- Produces (all exported from `lib/readings.ts`):
  - `DAY_MS: number`, `BACKUP_OLD_DAYS = 2`, `SYNC_GRACE_DAYS = 2`, `VRAM_FULL = 0.85`
  - `percent(n: number, of: number): number`
  - `daysSince(iso: string, now: Date): number`
  - `age(iso: string, now: Date): string`
  - `isBackupOld(at: string | null, now: Date): boolean`
  - `isSyncOld(at: string | null, autoDays: number, now: Date): boolean`
  - `servicesReading(s: AdminStatus["services"]): { ok: boolean; text: string }`
  - `recallReading(k: number, v: number | null | undefined): string | null`
  - `gpuShareReading(share: number | null | undefined): string | null`
  - `vramReading(usedMib: number, totalMib: number): string | null`
  - `rateReading(n: number, of: number, noun: string): string`
  - `indexReading(index: { documents: number; chunks: number; excluded: number } | null): string | null`
  - `countsLine(r: Record<string, number>): string`

- [ ] **Step 1: Create the branch**

```bash
cd "C:/dev/Second Brain" && git switch -c admin-tabs
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/lib/readings.test.ts`:

```ts
// Run with: npm test (node's own runner; pure functions, `now` passed in)
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  age,
  countsLine,
  gpuShareReading,
  indexReading,
  isBackupOld,
  isSyncOld,
  percent,
  rateReading,
  recallReading,
  servicesReading,
  vramReading,
} from "./readings.ts";

const NOW = new Date("2026-09-30T12:00:00Z");
const before = (hours: number) => new Date(NOW.getTime() - hours * 3_600_000).toISOString();

test("percent rounds to a whole number", () => {
  assert.equal(percent(1, 3), 33);
  assert.equal(percent(2, 3), 67);
});

test("age reads like the rest of the app", () => {
  assert.equal(age(before(0.01), NOW), "just now");
  assert.equal(age(before(0.5), NOW), "30 min ago");
  assert.equal(age(before(5), NOW), "5 h ago");
  assert.equal(age(before(72), NOW), "3 days ago");
});

test("a backup is old after 2 days, or when there is none", () => {
  assert.equal(isBackupOld(null, NOW), true);
  assert.equal(isBackupOld(before(47), NOW), false);
  assert.equal(isBackupOld(before(49), NOW), true);
});

test("a sync is old after auto_days + 2 days, or when there is none", () => {
  assert.equal(isSyncOld(null, 7, NOW), true);
  assert.equal(isSyncOld(before(24 * 8), 7, NOW), false);
  assert.equal(isSyncOld(before(24 * 10), 7, NOW), true);
  assert.equal(isSyncOld(before(24 * 3), 0, NOW), true);
});

test("servicesReading names the first thing that's down", () => {
  const ollama = { reachable: true, llm_pulled: true, embed_pulled: true };
  assert.deepEqual(servicesReading(null), { ok: false, text: "Couldn't check the services." });
  assert.equal(servicesReading({ db: { ok: false }, ollama }).text, "Database offline. Run docker compose up.");
  assert.equal(
    servicesReading({ db: { ok: true }, ollama: { reachable: false } }).text,
    "Ollama isn't running. Start it from the tray or run ollama serve.",
  );
  assert.equal(
    servicesReading({ db: { ok: true }, ollama: { ...ollama, embed_pulled: false } }).text,
    "A model isn't pulled yet. See the README setup.",
  );
  assert.deepEqual(servicesReading({ db: { ok: true }, ollama }), {
    ok: true,
    text: "Database, Ollama and both models ready",
  });
});

test("recallReading says where the right page lands", () => {
  assert.equal(recallReading(5, 0.84), "the right page is in the top 5 for 84% of questions");
  assert.equal(recallReading(1, 0.562), "the right page comes first for 56% of questions");
  assert.equal(recallReading(5, 0), "the right page is in the top 5 for 0% of questions");
  assert.equal(recallReading(5, null), null);
  assert.equal(recallReading(5, undefined), null);
});

test("gpuShareReading warns when the model spills onto the CPU", () => {
  assert.equal(gpuShareReading(1), "all on the GPU: full speed");
  assert.equal(gpuShareReading(0.72), "72% on the GPU; the rest runs on the CPU, so answers are slower");
  assert.equal(gpuShareReading(0), "all on the CPU, so answers are much slower");
  assert.equal(gpuShareReading(null), null);
});

test("vramReading flags 85% and above as nearly full", () => {
  assert.equal(vramReading(1024, 4096), "3.0 GB free");
  assert.equal(vramReading(3500, 4096), "nearly full: a larger context window may push the model onto the CPU");
  assert.equal(vramReading(0, 0), null);
});

test("rateReading gives the count, the total and the share", () => {
  assert.equal(rateReading(3, 40, "answers"), "3 of 40 answers (8%)");
  assert.equal(rateReading(0, 0, "answers"), "no answers yet");
});

test("indexReading describes the index in files and passages", () => {
  assert.equal(
    indexReading({ documents: 1240, chunks: 18034, excluded: 3 }),
    "1,240 files · 18,034 passages · 3 excluded from answers",
  );
  assert.equal(indexReading({ documents: 2, chunks: 9, excluded: 0 }), "2 files · 9 passages · nothing excluded");
  assert.equal(indexReading(null), null);
});

test("countsLine lists what an ingest run did", () => {
  assert.equal(countsLine({ indexed: 2, already_had: 5 }), "2 indexed, 5 already had");
  assert.equal(countsLine({}), "nothing to do");
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "C:/dev/Second Brain/frontend" && npm test`
Expected: FAIL. `readings.test.ts` can't find the module `./readings.ts`. The scratchpad tests still pass.

- [ ] **Step 4: Write the implementation**

Create `frontend/lib/readings.ts`:

```ts
/**
 * Plain-language readings of admin numbers: each turns a value into a short sentence, or null when
 * there is nothing to read. Pure (tested with node's runner); `now` is always passed in.
 */
import type { AdminStatus } from "./api.ts";

export const DAY_MS = 86_400_000;
export const BACKUP_OLD_DAYS = 2;
export const SYNC_GRACE_DAYS = 2;
export const VRAM_FULL = 0.85;

export const percent = (n: number, of: number): number => Math.round((n / of) * 100);

export const daysSince = (iso: string, now: Date): number => (now.getTime() - new Date(iso).getTime()) / DAY_MS;

/** "just now", "30 min ago", "5 h ago", "3 days ago": the same steps as `ago` in seen.ts. */
export function age(iso: string, now: Date): string {
  const s = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export const isBackupOld = (at: string | null, now: Date): boolean =>
  at === null || daysSince(at, now) > BACKUP_OLD_DAYS;

export const isSyncOld = (at: string | null, autoDays: number, now: Date): boolean =>
  at === null || daysSince(at, now) > autoDays + SYNC_GRACE_DAYS;

/** The first service that's down, in the order that blocks answers. */
export function servicesReading(s: AdminStatus["services"]): { ok: boolean; text: string } {
  if (!s) return { ok: false, text: "Couldn't check the services." };
  if (!s.db.ok) return { ok: false, text: "Database offline. Run docker compose up." };
  if (!s.ollama.reachable) return { ok: false, text: "Ollama isn't running. Start it from the tray or run ollama serve." };
  if (!s.ollama.llm_pulled || !s.ollama.embed_pulled)
    return { ok: false, text: "A model isn't pulled yet. See the README setup." };
  return { ok: true, text: "Database, Ollama and both models ready" };
}

export function recallReading(k: number, v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  const p = Math.round(v * 100);
  return k === 1
    ? `the right page comes first for ${p}% of questions`
    : `the right page is in the top ${k} for ${p}% of questions`;
}

export function gpuShareReading(share: number | null | undefined): string | null {
  if (share === null || share === undefined) return null;
  if (share >= 0.995) return "all on the GPU: full speed";
  if (share <= 0) return "all on the CPU, so answers are much slower";
  return `${Math.round(share * 100)}% on the GPU; the rest runs on the CPU, so answers are slower`;
}

export function vramReading(usedMib: number, totalMib: number): string | null {
  if (!(totalMib > 0)) return null;
  if (usedMib / totalMib >= VRAM_FULL) return "nearly full: a larger context window may push the model onto the CPU";
  return `${((totalMib - usedMib) / 1024).toFixed(1)} GB free`;
}

export function rateReading(n: number, of: number, noun: string): string {
  if (of === 0) return `no ${noun} yet`;
  return `${n} of ${of} ${noun} (${percent(n, of)}%)`;
}

export function indexReading(index: { documents: number; chunks: number; excluded: number } | null): string | null {
  if (!index) return null;
  const f = (n: number) => n.toLocaleString("en-GB");
  const excluded = index.excluded ? `${f(index.excluded)} excluded from answers` : "nothing excluded";
  return `${f(index.documents)} files · ${f(index.chunks)} passages · ${excluded}`;
}

/** What an ingest run did: "2 indexed, 5 already had". */
export const countsLine = (r: Record<string, number>): string =>
  Object.entries(r)
    .map(([k, n]) => `${n} ${k.replace("_", " ")}`)
    .join(", ") || "nothing to do";
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "C:/dev/Second Brain/frontend" && npm test`
Expected: PASS (all readings tests and the scratchpad tests).

- [ ] **Step 6: Commit**

```bash
cd "C:/dev/Second Brain" && git add frontend/lib/readings.ts frontend/lib/readings.test.ts && git commit -m "Admin readings: numbers as plain sentences, ages, and when a backup or sync is old

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Attention rules

**Files:**
- Create: `frontend/lib/attention.ts`
- Test: `frontend/lib/attention.test.ts`

**Interfaces:**
- Consumes (from Task 1): `daysSince`, `isBackupOld`, `isSyncOld`, `percent` and `servicesReading` from `./readings.ts`. Types `AdminLibrary`, `AdminStatus`, `InsightsSummary` and `SyncStatus` from `./api.ts` (type-only).
- Produces:
  - `type Severity = "bad" | "warn" | "info"`
  - `type AdminTab = "overview" | "library" | "quality" | "settings"`
  - `type AttentionItem = { id: string; severity: Severity; text: string; tab: AdminTab; href: string }`
  - `type Input<T> = T | null | "failed"` (`null` means still loading)
  - `type AttentionInputs = { status: Input<AdminStatus>; library: Input<AdminLibrary>; sync: Input<SyncStatus>; insights: Input<InsightsSummary>; now: Date }`
  - `INVALID_MAX = 0.1`, `REFUSED_MAX = 0.25`, `MIN_QUESTIONS = 10`
  - `attention(i: AttentionInputs): AttentionItem[]`, sorted bad → warn → info (stable)
  - `badgeCounts(items: AttentionItem[]): Record<AdminTab, number>`
  - Item ids: `failed:status`, `failed:library`, `failed:sync`, `failed:insights`, `services`, `backup`, `bb-login`, `bb-failed`, `bb-old`, `unreadable`, `summaries`, `invalid`, `refused`

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/attention.test.ts`:

```ts
// Run with: npm test (node's own runner; the rules are pure)
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AdminLibrary, AdminStatus, InsightsSummary, SyncJob, SyncStatus } from "./api.ts";
import { type AttentionInputs, attention, badgeCounts } from "./attention.ts";

const NOW = new Date("2026-09-30T12:00:00Z");
const daysAgo = (d: number) => new Date(NOW.getTime() - d * 86_400_000).toISOString();

const status = (over: Partial<AdminStatus> = {}): AdminStatus => ({
  services: { db: { ok: true }, ollama: { reachable: true, llm_pulled: true, embed_pulled: true } },
  reranker: null,
  llm: null,
  gpu: { available: false },
  answers: null,
  index: null,
  backup: { name: "b", at: daysAgo(0.5), bytes: 1, kept: 3 },
  enrichment: null,
  ...over,
});
const library = (over: Partial<AdminLibrary> = {}): AdminLibrary => ({
  modules: [],
  problems: [],
  excluded: [],
  summary_errors: [],
  ...over,
});
const run = (state: SyncJob["state"], over: Partial<SyncJob> = {}): SyncJob => ({
  id: 1,
  mode: "sync",
  course: null,
  started_at: daysAgo(1),
  finished_at: daysAgo(1),
  state,
  exit_code: 0,
  counts: { downloaded: 0, saved_page: 0, already_had: 0, would_download: 0, would_save_page: 0, failed: 0 },
  bytes: 0,
  error: null,
  ...over,
});
const sync = (over: Partial<SyncStatus> = {}): SyncStatus => ({
  job: null,
  runs: [run("ok")],
  login_needed: false,
  last_full_sync: daysAgo(1),
  next_auto: null,
  auto_days: 7,
  modules: [],
  ...over,
});
const insights = (over: Partial<InsightsSummary> = {}): InsightsSummary => ({
  questions: 40,
  refused: 2,
  invalid: 1,
  failed: 0,
  median_ms: 9000,
  max_ms: 30000,
  per_module: [],
  per_day: [],
  ...over,
});
const healthy = (over: Partial<AttentionInputs> = {}): AttentionInputs => ({
  status: status(),
  library: library(),
  sync: sync(),
  insights: insights(),
  now: NOW,
  ...over,
});
const ids = (i: AttentionInputs) => attention(i).map((x) => x.id);
const problem = { id: 1, path: "p.pdf", title: "P", course: null, status: "error" as const, error: null };

test("a healthy cabinet needs nothing", () => {
  assert.deepEqual(attention(healthy()), []);
});

test("inputs still loading add nothing", () => {
  assert.deepEqual(attention({ status: null, library: null, sync: null, insights: null, now: NOW }), []);
});

test("a failed input says what couldn't be checked, linked to its page", () => {
  const items = attention(healthy({ sync: "failed", insights: "failed" }));
  assert.deepEqual(
    items.map((x) => [x.id, x.severity, x.text, x.tab, x.href]),
    [
      ["failed:sync", "warn", "Couldn't check the Blackboard sync.", "library", "/admin/library#sync"],
      ["failed:insights", "warn", "Couldn't check recent answers.", "quality", "/admin/quality#insights"],
    ],
  );
});

test("a service down is bad and points at the system details", () => {
  const [item] = attention(healthy({ status: status({ services: { db: { ok: false }, ollama: { reachable: true } } }) }));
  assert.equal(item.id, "services");
  assert.equal(item.severity, "bad");
  assert.equal(item.text, "Database offline. Run docker compose up.");
  assert.equal(item.href, "/admin#details");
});

test("no backup, or one older than 2 days, is a warning pointing at the actions", () => {
  assert.deepEqual(ids(healthy({ status: status({ backup: null }) })), ["backup"]);
  const [old] = attention(healthy({ status: status({ backup: { name: "b", at: daysAgo(3), bytes: 1, kept: 3 } }) }));
  assert.equal(old.text, "The last backup is 3 days old. Back up now so a reset can't lose your history.");
  assert.equal(old.href, "/admin#actions");
  assert.deepEqual(ids(healthy({ status: status({ backup: { name: "b", at: daysAgo(1.9), bytes: 1, kept: 3 } }) })), []);
});

test("a Blackboard login needed is bad, and hides the other sync items", () => {
  assert.deepEqual(ids(healthy({ sync: sync({ login_needed: true, runs: [run("failed")], last_full_sync: null }) })), [
    "bb-login",
  ]);
});

test("the last finished sync run failing is bad; running and non-sync runs are skipped", () => {
  const failed = run("failed", { error: "timeout" });
  const [item] = attention(healthy({ sync: sync({ runs: [run("running"), run("ok", { mode: "preview" }), failed] }) }));
  assert.equal(item.id, "bb-failed");
  assert.equal(item.text, "The last Blackboard sync failed: timeout. New course files may be missing.");
  assert.deepEqual(ids(healthy({ sync: sync({ runs: [run("login_required")] }) })), ["bb-failed"]);
});

test("a full sync older than auto_days + 2 is a warning", () => {
  assert.deepEqual(ids(healthy({ sync: sync({ last_full_sync: daysAgo(8.5) }) })), []);
  const [item] = attention(healthy({ sync: sync({ last_full_sync: daysAgo(10) }) }));
  assert.equal(item.id, "bb-old");
  assert.equal(item.text, "No full Blackboard sync for 10 days, so recent course files may be missing.");
  assert.equal(
    attention(healthy({ sync: sync({ last_full_sync: null }) }))[0].text,
    "You haven't run a full Blackboard sync from here yet.",
  );
});

test("unreadable files warn, failed summaries are only info", () => {
  const items = attention(healthy({ library: library({ problems: [problem, { ...problem, id: 2 }], summary_errors: [problem] }) }));
  assert.deepEqual(
    items.map((x) => [x.id, x.severity, x.text]),
    [
      ["unreadable", "warn", "2 files couldn't be read, so their pages never appear in answers."],
      ["summaries", "info", "1 file couldn't be summarised. It still appears in answers."],
    ],
  );
});

test("invalid citations warn above 10%, refusals above 25%, with at least 10 questions", () => {
  assert.deepEqual(ids(healthy({ insights: insights({ questions: 40, invalid: 4, refused: 10 }) })), []);
  assert.deepEqual(ids(healthy({ insights: insights({ questions: 40, invalid: 5, refused: 11 }) })), ["invalid", "refused"]);
  assert.deepEqual(ids(healthy({ insights: insights({ questions: 9, invalid: 9, refused: 9 }) })), []);
  const [item] = attention(healthy({ insights: insights({ questions: 40, invalid: 5 }) }));
  assert.equal(item.text, "13% of answers in the last 7 days had invalid citations (5 of 40).");
  assert.equal(item.href, "/admin/quality#insights");
});

test("items are sorted bad, then warn, then info", () => {
  const items = attention(
    healthy({
      status: status({ backup: null }),
      library: library({ summary_errors: [problem] }),
      sync: sync({ login_needed: true }),
    }),
  );
  assert.deepEqual(
    items.map((x) => x.severity),
    ["bad", "warn", "info"],
  );
});

test("badges count items per tab, leaving out info", () => {
  const items = attention(
    healthy({
      status: status({ backup: null }),
      library: library({ problems: [problem], summary_errors: [problem] }),
      sync: sync({ login_needed: true }),
    }),
  );
  assert.deepEqual(badgeCounts(items), { overview: 1, library: 2, quality: 0, settings: 0 });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "C:/dev/Second Brain/frontend" && npm test`
Expected: FAIL. `attention.test.ts` can't find the module `./attention.ts`.

- [ ] **Step 3: Write the implementation**

Create `frontend/lib/attention.ts`:

```ts
/**
 * What needs the student on the admin Overview, and the tab badges. Worked out in the browser from
 * four existing endpoints; pure (tested with node's runner). `null` input: still loading.
 */
import type { AdminLibrary, AdminStatus, InsightsSummary, SyncStatus } from "./api.ts";
import { daysSince, isBackupOld, isSyncOld, percent, servicesReading } from "./readings.ts";

export type Severity = "bad" | "warn" | "info";
export type AdminTab = "overview" | "library" | "quality" | "settings";
export type AttentionItem = { id: string; severity: Severity; text: string; tab: AdminTab; href: string };
export type Input<T> = T | null | "failed";
export type AttentionInputs = {
  status: Input<AdminStatus>;
  library: Input<AdminLibrary>;
  sync: Input<SyncStatus>;
  insights: Input<InsightsSummary>;
  now: Date;
};

export const INVALID_MAX = 0.1;
export const REFUSED_MAX = 0.25;
export const MIN_QUESTIONS = 10;

type Source = "status" | "library" | "sync" | "insights";
const WHERE: Record<Source, { tab: AdminTab; href: string; what: string }> = {
  status: { tab: "overview", href: "/admin#details", what: "the services" },
  library: { tab: "library", href: "/admin/library#library", what: "the library" },
  sync: { tab: "library", href: "/admin/library#sync", what: "the Blackboard sync" },
  insights: { tab: "quality", href: "/admin/quality#insights", what: "recent answers" },
};
const RANK: Record<Severity, number> = { bad: 0, warn: 1, info: 2 };
const files = (n: number) => `${n} file${n === 1 ? "" : "s"}`;

export function attention(i: AttentionInputs): AttentionItem[] {
  const out: AttentionItem[] = [];
  const add = (id: string, severity: Severity, text: string, from: Source, href = WHERE[from].href) =>
    out.push({ id, severity, text, tab: WHERE[from].tab, href });

  for (const from of ["status", "library", "sync", "insights"] as const)
    if (i[from] === "failed") add(`failed:${from}`, "warn", `Couldn't check ${WHERE[from].what}.`, from);

  const { status, library, sync, insights, now } = i;

  if (status && status !== "failed") {
    const svc = servicesReading(status.services);
    if (!svc.ok) add("services", "bad", svc.text, "status");
    const at = status.backup?.at ?? null;
    if (isBackupOld(at, now))
      add(
        "backup",
        "warn",
        at
          ? `The last backup is ${Math.floor(daysSince(at, now))} days old. Back up now so a reset can't lose your history.`
          : "There's no backup yet. The backend makes one a few minutes after it starts, or back up now.",
        "status",
        "/admin#actions",
      );
  }

  if (sync && sync !== "failed") {
    const last = sync.runs.find((r) => r.mode === "sync" && r.state !== "running");
    if (sync.login_needed)
      add("bb-login", "bad", "Blackboard needs you to log in again. Until then, syncs can't fetch new files.", "sync");
    else if (last?.state === "failed" || last?.state === "login_required")
      add(
        "bb-failed",
        "bad",
        last.state === "failed"
          ? `The last Blackboard sync failed${last.error ? `: ${last.error}` : ""}. New course files may be missing.`
          : "The last Blackboard sync stopped at the login page. New course files may be missing.",
        "sync",
      );
    else if (isSyncOld(sync.last_full_sync, sync.auto_days, now))
      add(
        "bb-old",
        "warn",
        sync.last_full_sync
          ? `No full Blackboard sync for ${Math.floor(daysSince(sync.last_full_sync, now))} days, so recent course files may be missing.`
          : "You haven't run a full Blackboard sync from here yet.",
        "sync",
      );
  }

  if (library && library !== "failed") {
    const n = library.problems.length;
    if (n)
      add(
        "unreadable",
        "warn",
        `${files(n)} couldn't be read, so ${n === 1 ? "its" : "their"} pages never appear in answers.`,
        "library",
      );
    const m = library.summary_errors.length;
    if (m)
      add(
        "summaries",
        "info",
        `${files(m)} couldn't be summarised. ${m === 1 ? "It still appears" : "They still appear"} in answers.`,
        "library",
      );
  }

  if (insights && insights !== "failed" && insights.questions >= MIN_QUESTIONS) {
    const q = insights.questions;
    if (insights.invalid / q > INVALID_MAX)
      add(
        "invalid",
        "warn",
        `${percent(insights.invalid, q)}% of answers in the last 7 days had invalid citations (${insights.invalid} of ${q}).`,
        "insights",
      );
    if (insights.refused / q > REFUSED_MAX)
      add(
        "refused",
        "warn",
        `${percent(insights.refused, q)}% of questions in the last 7 days were refused (${insights.refused} of ${q}). Material may be missing, or the refusal threshold is too high.`,
        "insights",
      );
  }

  return out.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

/** Problems per tab for the tab bar; info items show in the list but don't count. */
export function badgeCounts(items: AttentionItem[]): Record<AdminTab, number> {
  const c: Record<AdminTab, number> = { overview: 0, library: 0, quality: 0, settings: 0 };
  for (const it of items) if (it.severity !== "info") c[it.tab]++;
  return c;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "C:/dev/Second Brain/frontend" && npm test`
Expected: PASS (readings, attention and scratchpad).

- [ ] **Step 5: Commit**

```bash
cd "C:/dev/Second Brain" && git add frontend/lib/attention.ts frontend/lib/attention.test.ts && git commit -m "Admin attention rules: what needs the student, worked out from four endpoints, and badges per tab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Explanation copy and the Explain component

**Files:**
- Create: `frontend/lib/adminHelp.ts`
- Create: `frontend/components/admin/Explain.tsx`
- Modify: `frontend/app/globals.css` (append after the `/* ---- admin settings` block's `.setting .help` rule)

**Interfaces:**
- Consumes: the `AdminTab` type from `lib/attention.ts`.
- Produces:
  - `type Help = { line: string; more: string }`
  - `pageIntro: Record<AdminTab, string>`
  - `actionHelp: Record<"sync" | "backup" | "rescan" | "enrich" | "reindex" | "reenrich" | "exclude" | "vocab", Help>`
  - `settingMore: Record<string, string>`, keyed by the backend setting key (`retrieval_mode`, `rerank`, `top_k`, `candidate_k`, `rrf_k`, `min_score`, `doc_boost`, `llm_model`, `temperature`, `doc_context`, `num_ctx`, `llm_keep_alive`, `sync_auto_days`)
  - `metricHelp: Record<string, string>`, keyed by `recall@1`, `recall@5`, `recall@20`, `mrr`, `refusal_rate`, `citation_valid_rate`, `cited_right_rate`, `invalid`, `refused`
  - `detailHelp: Record<"llm" | "reranker" | "gpu" | "answers" | "index" | "summaries", string>`
  - `<Explain line?: string | null; more?: string | null />`, which renders nothing when both are empty

- [ ] **Step 1: Write the copy**

Create `frontend/lib/adminHelp.ts`:

```ts
/** Every explanation in the admin panel, in one place so the wording stays consistent. */
import type { AdminTab } from "./attention.ts";

export type Help = { line: string; more: string };

export const pageIntro: Record<AdminTab, string> = {
  overview: "Start here: what needs you, the everyday actions, and whether everything is running.",
  library: "What's in the cabinet: files that couldn't be read, tags, and syncing from Blackboard.",
  quality: "How good the answers are: your recent questions, and measured runs to test a settings change before keeping it.",
  settings: "How answers are found and written. Changes apply from the next question, with no restart.",
};

export const actionHelp: Record<
  "sync" | "backup" | "rescan" | "enrich" | "reindex" | "reenrich" | "exclude" | "vocab",
  Help
> = {
  sync: {
    line: "Checks Blackboard for new files, pages and deadlines · a few minutes",
    more: "Downloads new or changed files into each module's inbox folder, saves Ultra pages as notes, and imports calendar due dates as Planner to-dos. The backend indexes new files as they arrive. If your Blackboard session has expired, you'll be asked to log in first.",
  },
  backup: {
    line: "Saves your questions, planner, tags and evaluations · a few seconds",
    more: "Writes the query log, planner items, tags, evaluation runs and excluded files to the backups folder. The backend also backs up once a day and keeps the last 30. Course files aren't included: they stay in the inbox and can be indexed again.",
  },
  rescan: {
    line: "Looks for files added, changed or deleted in the inbox · unchanged files are skipped",
    more: "The backend watches the inbox while it runs. Rescan catches anything that changed while it was off. Use it if a file you added doesn't show up in the library.",
  },
  enrich: {
    line: "Summaries, concepts and tags are written in the background, one file at a time",
    more: "Pausing frees the GPU while you work; the queue waits until you resume. Summaries only feed the library and tags; they don't change how answers are found.",
  },
  reindex: {
    line: "Re-index reads a module or file again, even if it hasn't changed",
    more: "Use it when a file was read badly or after setting up OCR. The file's passages are replaced; questions keep working while it runs.",
  },
  reenrich: {
    line: "Re-enrich asks the model for new summaries, concepts and tags",
    more: "Use it when a summary is wrong or empty. It runs in the background like the first pass.",
  },
  exclude: {
    line: "Exclude keeps a file on disk but out of your answers",
    more: "The file's passages leave the index and rescans skip it. Include puts it back and indexes it again.",
  },
  vocab: {
    line: "The vocabulary pass merges near-duplicate tags in a module",
    more: "Tags that mean the same thing (for example 'gradient descent' and 'descente de gradient') are merged into one. Names you set yourself are kept.",
  },
};

export const settingMore: Record<string, string> = {
  retrieval_mode:
    "Dense finds passages by meaning. Hybrid adds keyword search and fuses the two lists. Dense won the evaluation (right page in the top 5: 84% against 72%), so it's the default. Try hybrid only if exact terms, like a formula name or an acronym, are being missed.",
  rerank:
    "A second model rereads the question with each candidate passage and reorders them. It put the right page first 56% of the time instead of 44%, for about 0.9 s more per question. Turn it off if answers feel too slow or VRAM is tight.",
  top_k:
    "More passages give the model more to cite, but make the prompt longer: slower answers and more VRAM. Fewer are faster but may miss the page you need. Default 5.",
  candidate_k:
    "How many passages are pulled before the reranker picks the best ones. More candidates give it more chances to find the right page, but each one adds rerank time. Default 20.",
  rrf_k:
    "Only used in hybrid mode. When the vector and keyword lists are fused, a higher value makes rank position matter less, so passages found by both lists beat a passage ranked first by only one. Default 60.",
  min_score:
    "If no passage is at least this close to the question, the question is refused without calling the model. Raise it for fewer off-topic answers but more refusals on real questions; lower it for the opposite. Default 0.35.",
  doc_boost:
    "Ranks passages higher when their file's summary matches the question. It measured within noise in the evaluation, so it stays at 0 (off).",
  llm_model:
    "The local model that writes answers. A larger model writes better but may not fit in 4 GB of VRAM; then part of it runs on the CPU and answers get much slower. Default qwen3:4b-instruct.",
  temperature:
    "How much the model varies its wording. Low values stay close to the passages, which is what you want for cited answers. Default 0.2.",
  doc_context:
    "Starts each passage the model reads with its file's summary. It measured no better and 28% slower in the evaluation, so it stays off.",
  num_ctx:
    "How many tokens the model sees at once: the passages plus its answer. A larger window fits more passages but uses more VRAM; past what fits, part of the model moves to the CPU. Default 4096, enough for 5 passages.",
  llm_keep_alive:
    "How long the model stays in VRAM after a question. Keeping it loaded avoids a reload of about 9 s during a revision session; unloading frees the GPU for other work. Default 30m.",
  sync_auto_days:
    "The backend runs a full Blackboard sync on its own this often. 0 turns it off; you can still sync from the Overview. Default 7.",
};

export const metricHelp: Record<string, string> = {
  "recall@1": "The share of test questions where the page the question was written from is ranked first.",
  "recall@5":
    "The share where that page is among the top 5 passages: the ones the model actually reads with the default settings. This is the number that matters most.",
  "recall@20":
    "The share where it's among the top 20 candidates. If this is high but the top 5 is low, the right page is found but ranked too low; the reranker helps there.",
  mrr: "Mean reciprocal rank: 1 when the right page is first, 0.5 when second, 0.33 when third, and so on, averaged. 1 is perfect.",
  refusal_rate:
    "Questions refused because no passage passed the refusal threshold. Every test question has an answer, so each refusal here is a miss.",
  citation_valid_rate: "Answers where every [n] points to a passage the model was actually given.",
  cited_right_rate: "Answers that cite the page the question was written from.",
  invalid:
    "An answer whose [n] doesn't match a passage it was given. The answer is flagged when it happens. If this grows, try a lower temperature or the default model.",
  refused:
    "Questions answered with 'not in your fiches' because no passage was close enough. Many refusals mean material is missing or the refusal threshold is too high.",
};

export const detailHelp: Record<"llm" | "reranker" | "gpu" | "answers" | "index" | "summaries", string> = {
  llm: "The share of the model held in VRAM. Below 100%, the rest runs on the CPU and answers take several times longer. A smaller context window or model helps.",
  reranker: "Loads on the first question and leaves the GPU after 30 idle minutes.",
  gpu: "The RTX 2050's 4 GB are shared by the answer model and the reranker. When it's nearly full, the model spills onto the CPU.",
  answers:
    "Time from asking to the last word, over recent questions. 5 to 60 s is normal on this laptop, depending on what else is using the GPU.",
  index:
    "Passages are pieces of about 500 tokens cut from your files; the model reads the closest ones. OCR reads text inside images in PDFs, slides and Word files.",
  summaries: "Written by the local model after indexing, for the library and tags. They don't change how answers are found.",
};
```

- [ ] **Step 2: Write the component**

Create `frontend/components/admin/Explain.tsx`:

```tsx
/** A plain-language reading beside a number, setting or action, with an optional longer "How it works". */
export function Explain({ line, more }: { line?: string | null; more?: string | null }) {
  if (!line && !more) return null;
  return (
    <div className="explain">
      {line && <p className="explain-line">{line}</p>}
      {more && (
        <details className="explain-more">
          <summary>How it works</summary>
          <p>{more}</p>
        </details>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add the base styles**

Append to `frontend/app/globals.css` right after the `.setting .help { … }` rule (the Task 7 design pass refines these):

```css
/* ---- admin: explanations (an inline reading, then "How it works") ---------------------- */
.explain {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.82rem;
  color: var(--muted);
}

.explain p {
  margin: 0;
}

.explain-more summary {
  cursor: pointer;
  width: fit-content;
  color: var(--primary);
}

.explain-more[open] p {
  max-width: var(--measure);
  margin-top: 0.2rem;
}
```

- [ ] **Step 4: Check types and lint**

Run: `cd "C:/dev/Second Brain/frontend" && npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd "C:/dev/Second Brain" && git add frontend/lib/adminHelp.ts frontend/components/admin/Explain.tsx frontend/app/globals.css && git commit -m "Admin explanations: page intros, settings, actions, metrics and details in one file; the Explain component

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The tabbed shell (layout, data provider, the four routes)

**Files:**
- Create: `frontend/components/admin/AdminData.tsx`
- Create: `frontend/app/admin/layout.tsx`
- Rewrite: `frontend/app/admin/page.tsx` (temporarily renders `StatusCard`; Task 5 replaces it)
- Create: `frontend/app/admin/library/page.tsx`, `frontend/app/admin/quality/page.tsx`, `frontend/app/admin/settings/page.tsx`
- Modify: `frontend/components/admin/LibraryAdmin.tsx` (section `id="library"`), `TagsCard.tsx` (`id="tags"`), `InsightsCard.tsx` (`id="insights"`), `EvalCard.tsx` (`id="eval"`). `SyncCard` already has `id="sync"`.
- Modify: `frontend/components/Rail.tsx:124`
- Modify: `frontend/app/globals.css` (tab bar and badge)

**Interfaces:**
- Consumes: `attention`, `badgeCounts`, `AdminTab` and `AttentionItem` from `@/lib/attention`; `pageIntro` from `@/lib/adminHelp`; `getJSON` and the endpoint types from `@/lib/api`.
- Produces: from `components/admin/AdminData.tsx`, `AdminDataProvider` and `useAdminData(): AdminData`, where

```ts
type Slot<T> = { value: T | null; failed: boolean }; // value keeps the last good reading after a failure
type AdminData = {
  status: Slot<AdminStatus>;
  library: Slot<AdminLibrary>;
  sync: Slot<SyncStatus>;
  insights: Slot<InsightsSummary>; // last 7 days
  items: AttentionItem[];
  badges: Record<AdminTab, number>;
  offline: boolean; // all four failed
  now: Date; // when the last poll finished
  refresh: () => void;
};
```

- [ ] **Step 1: Read the Next 16 docs for layouts and `usePathname`**

Run: `cd "C:/dev/Second Brain/frontend" && ls node_modules/next/dist/docs/01-app/01-getting-started/`. Then read the layouts-and-pages guide and `04-linking-and-navigating.md`. Confirm that nested `layout.tsx` works, that the global `LayoutProps<"/admin">` type exists (the root layout already uses `LayoutProps<"/">`), and that `<Link href="/x#id">` scrolls to the id. If any of these differ, follow the docs and note the change in the commit message.

- [ ] **Step 2: Write the data provider**

Create `frontend/components/admin/AdminData.tsx`:

```tsx
"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { type AdminLibrary, type AdminStatus, getJSON, type InsightsSummary, type SyncStatus } from "@/lib/api";
import { type AdminTab, type AttentionItem, attention, badgeCounts } from "@/lib/attention";

const POLL_MS = 10_000;

/** One endpoint's reading; `value` keeps the last good reading after a failure. */
export type Slot<T> = { value: T | null; failed: boolean };
export type AdminData = {
  status: Slot<AdminStatus>;
  library: Slot<AdminLibrary>;
  sync: Slot<SyncStatus>;
  insights: Slot<InsightsSummary>;
  items: AttentionItem[];
  badges: Record<AdminTab, number>;
  offline: boolean;
  now: Date;
  refresh: () => void;
};

const EMPTY = { value: null, failed: false };
const input = <T,>(s: Slot<T>) => (s.failed ? ("failed" as const) : s.value);
const Ctx = createContext<AdminData | null>(null);

export function useAdminData(): AdminData {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAdminData is only available inside the admin layout");
  return v;
}

/** Polls what the Overview and the tab badges need, every 10 s while the tab is visible. */
export function AdminDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Slot<AdminStatus>>(EMPTY);
  const [library, setLibrary] = useState<Slot<AdminLibrary>>(EMPTY);
  const [sync, setSync] = useState<Slot<SyncStatus>>(EMPTY);
  const [insights, setInsights] = useState<Slot<InsightsSummary>>(EMPTY);
  const [now, setNow] = useState(() => new Date());

  const refresh = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const pull = <T,>(path: string, set: Dispatch<SetStateAction<Slot<T>>>) =>
      getJSON<T>(path).then(
        (value) => set({ value, failed: false }),
        () => set((prev) => ({ value: prev.value, failed: true })),
      );
    Promise.all([
      pull("/admin/status", setStatus),
      pull("/admin/library", setLibrary),
      pull("/admin/sync", setSync),
      pull(`/admin/insights?days=7&tz=${encodeURIComponent(tz)}`, setInsights),
    ]).then(() => setNow(new Date()));
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [refresh]);

  const value = useMemo<AdminData>(() => {
    const items = attention({
      status: input(status),
      library: input(library),
      sync: input(sync),
      insights: input(insights),
      now,
    });
    return {
      status,
      library,
      sync,
      insights,
      items,
      badges: badgeCounts(items),
      offline: status.failed && library.failed && sync.failed && insights.failed,
      now,
      refresh,
    };
  }, [status, library, sync, insights, now, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
```

- [ ] **Step 3: Write the layout**

Create `frontend/app/admin/layout.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AdminDataProvider, useAdminData } from "@/components/admin/AdminData";
import { pageIntro } from "@/lib/adminHelp";
import type { AdminTab } from "@/lib/attention";

const TABS: { tab: AdminTab; href: string; label: string }[] = [
  { tab: "overview", href: "/admin", label: "Overview" },
  { tab: "library", href: "/admin/library", label: "Library" },
  { tab: "quality", href: "/admin/quality", label: "Quality" },
  { tab: "settings", href: "/admin/settings", label: "Settings" },
];

const activeTab = (path: string): AdminTab => TABS.slice(1).find((t) => path.startsWith(t.href))?.tab ?? "overview";

function Shell({ children }: { children: ReactNode }) {
  const tab = activeTab(usePathname());
  const { badges, offline } = useAdminData();
  return (
    <div className="drawer-view admin-view">
      <header className="drawer-head">
        <h1>Admin</h1>
        <p>{pageIntro[tab]}</p>
      </header>
      <nav className="admin-tabs" aria-label="Admin sections">
        {TABS.map((t) => (
          <Link key={t.tab} href={t.href} aria-current={t.tab === tab ? "page" : undefined}>
            {t.label}
            {badges[t.tab] > 0 && (
              <span className="admin-badge">
                {badges[t.tab]}
                <span className="sr-only"> need attention</span>
              </span>
            )}
          </Link>
        ))}
      </nav>
      {offline && <p className="notice bad">Backend offline. Start it with uvicorn.</p>}
      {children}
    </div>
  );
}

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminDataProvider>
      <Shell>{children}</Shell>
    </AdminDataProvider>
  );
}
```

- [ ] **Step 4: Write the four pages**

Replace `frontend/app/admin/page.tsx` with this (a temporary Overview; Task 5 replaces it):

```tsx
import { StatusCard } from "@/components/admin/StatusCard";

export default function AdminOverview() {
  return <StatusCard />;
}
```

Create `frontend/app/admin/library/page.tsx`:

```tsx
import { LibraryAdmin } from "@/components/admin/LibraryAdmin";
import { SyncCard } from "@/components/admin/SyncCard";
import { TagsCard } from "@/components/admin/TagsCard";

export default function AdminLibrary() {
  return (
    <>
      <LibraryAdmin />
      <TagsCard />
      <SyncCard />
    </>
  );
}
```

Create `frontend/app/admin/quality/page.tsx`:

```tsx
import { EvalCard } from "@/components/admin/EvalCard";
import { InsightsCard } from "@/components/admin/InsightsCard";

export default function AdminQuality() {
  return (
    <>
      <InsightsCard />
      <EvalCard />
    </>
  );
}
```

Create `frontend/app/admin/settings/page.tsx`:

```tsx
import { SettingsCard } from "@/components/admin/SettingsCard";

export default function AdminSettings() {
  return <SettingsCard />;
}
```

- [ ] **Step 5: Add section ids for the deep links**

- `LibraryAdmin.tsx`: `<section className="admin-card" aria-labelledby="library-h">` becomes `<section className="admin-card" id="library" aria-labelledby="library-h">`
- `TagsCard.tsx`: `<section className="admin-card" aria-labelledby="tags-h">` becomes `<section className="admin-card" id="tags" aria-labelledby="tags-h">`
- `InsightsCard.tsx`: `<section className="admin-card" aria-labelledby="insights-h">` becomes `<section className="admin-card" id="insights" aria-labelledby="insights-h">`
- `EvalCard.tsx`: `<section className="admin-card" aria-labelledby="eval-h">` becomes `<section className="admin-card" id="eval" aria-labelledby="eval-h">`

- [ ] **Step 6: Point the rail's login link at the Library tab**

In `frontend/components/Rail.tsx`, change `<Link href="/admin#sync" className="bb-login">` to `<Link href="/admin/library#sync" className="bb-login">`.

- [ ] **Step 7: Style the tab bar**

Append to `frontend/app/globals.css` after the `.admin-card .quiet-btn` rule:

```css
/* ---- admin: the tab bar ---------------------------------------------------------------------- */
.admin-tabs {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--rule-blue);
}

.admin-tabs a {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.8rem;
  border-radius: 4px 4px 0 0;
  color: var(--muted);
  text-decoration: none;
}

.admin-tabs a:hover {
  color: var(--ink);
}

.admin-tabs a[aria-current="page"] {
  background: var(--card);
  color: var(--ink);
  box-shadow: inset 0 -2px 0 var(--primary);
}

.admin-badge {
  min-width: 1.25rem;
  padding: 0 0.35rem;
  border-radius: 999px;
  background: var(--bad);
  color: var(--card);
  font-size: 0.72rem;
  line-height: 1.25rem;
  text-align: center;
}
```

- [ ] **Step 8: Check types, lint, tests and the build**

Run: `cd "C:/dev/Second Brain/frontend" && npx next typegen && npx tsc --noEmit && npm run lint && npm test && npm run build`
Expected: no errors; all tests pass; the build lists `/admin`, `/admin/library`, `/admin/quality` and `/admin/settings`.
- `next typegen` regenerates the route types that `LayoutProps<"/admin">` needs. If this Next version has no `typegen` command, `npm run build` generates them; run `tsc` after it instead.
- The build is also the first real check that the bundler accepts `lib/attention.ts` importing `./readings.ts` with its extension. If it fails there, confirm `allowImportingTsExtensions` in `tsconfig.json` and read the Next docs on TypeScript config before changing anything.

- [ ] **Step 9: Check it in the browser**

Start the backend and frontend from the main checkout (`preview_start` with `backend`, then `frontend`) and open `http://localhost:3000/admin`. Check each item:
- The four tabs switch pages, and the URL changes to `/admin`, `/admin/library`, `/admin/quality` and `/admin/settings`.
- The intro line under "Admin" changes per tab.
- `http://localhost:3000/admin/library#sync` scrolls to the Blackboard sync card.
- Badges show on tabs with problems (compare with the old cards' contents) and are absent otherwise.
- `read_console_messages` with `onlyErrors: true` shows no errors.

- [ ] **Step 10: Commit**

```bash
cd "C:/dev/Second Brain" && git add -A frontend/app/admin frontend/components/admin frontend/components/Rail.tsx frontend/app/globals.css && git commit -m "Admin in four tabs: Overview, Library, Quality, Settings, with badges from the attention rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The Overview (needs attention, actions, tiles, system details)

**Files:**
- Create: `frontend/components/admin/NeedsAttention.tsx`, `ActionStrip.tsx`, `GlanceTiles.tsx`, `SystemDetails.tsx`
- Rewrite: `frontend/app/admin/page.tsx`
- Delete: `frontend/components/admin/StatusCard.tsx`
- Modify: `frontend/components/admin/LibraryAdmin.tsx` (use `countsLine` from readings instead of its local `counts`)
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `useAdminData()` (Task 4); `Explain` and `actionHelp`/`detailHelp` (Task 3); `age`, `countsLine`, `gpuShareReading`, `indexReading`, `isBackupOld`, `isSyncOld`, `servicesReading` and `vramReading` (Task 1); `postJSON`, `EnrichmentStatus` and `SyncStatus` from `@/lib/api`; `ago` from `@/lib/seen`.
- Produces: `NeedsAttention`, `ActionStrip`, `GlanceTiles` and `SystemDetails`, all without props.

- [ ] **Step 1: Write NeedsAttention**

Create `frontend/components/admin/NeedsAttention.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useAdminData } from "@/components/admin/AdminData";
import type { Severity } from "@/lib/attention";

const SEVERITY: Record<Severity, string> = { bad: "Problem", warn: "Check", info: "Note" };

/** What needs the student, most urgent first; each item links to where it's fixed. */
export function NeedsAttention() {
  const { items, status, library, sync, insights, offline } = useAdminData();
  if (offline) return null; // the layout already says the backend is offline
  const loading = [status, library, sync, insights].some((s) => s.value === null && !s.failed);
  return (
    <section className="admin-card attention" aria-labelledby="attention-h">
      <h2 id="attention-h">Needs attention</h2>
      {items.length === 0 ? (
        <p className="muted">
          {loading ? "Checking the cabinet…" : "Nothing needs you. Everything is running and up to date."}
        </p>
      ) : (
        <ul className="attention-list">
          {items.map((it) => (
            <li key={it.id} className={`attention-item ${it.severity}`}>
              <span className="sr-only">{SEVERITY[it.severity]}: </span>
              <Link href={it.href}>{it.text}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Write ActionStrip**

Create `frontend/components/admin/ActionStrip.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { useAdminData } from "@/components/admin/AdminData";
import { Explain } from "@/components/admin/Explain";
import { type EnrichmentStatus, postJSON } from "@/lib/api";
import { actionHelp, type Help } from "@/lib/adminHelp";
import { countsLine } from "@/lib/readings";

type Note = { text: string; bad?: boolean } | null;

/** One everyday action: a button, what it does, and its result. */
function Action(props: {
  label: string;
  busyLabel: string;
  help: Help;
  disabled?: boolean;
  run: () => Promise<string>;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  async function go() {
    setBusy(true);
    setNote(null);
    try {
      setNote({ text: await props.run() });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="action">
      <button type="button" className="quiet-btn" onClick={go} disabled={busy || props.disabled}>
        {busy ? props.busyLabel : props.label}
      </button>
      <Explain line={props.help.line} more={props.help.more} />
      {note && (
        <p className={`action-note${note.bad ? " bad" : ""}`} aria-live="polite">
          {note.text}
        </p>
      )}
    </div>
  );
}

/** Sync, back up, rescan and pause summaries: the things done most days, in one place. */
export function ActionStrip() {
  const { status, sync, refresh } = useAdminData();
  const syncing = sync.value?.job?.state === "running";
  const enrich = status.value?.enrichment ?? null;
  const after = async (text: string) => {
    refresh();
    return text;
  };

  return (
    <section className="admin-card" id="actions" aria-labelledby="actions-h">
      <h2 id="actions-h">Everyday actions</h2>
      <div className="action-strip">
        <Action
          label={syncing ? "Syncing…" : "Sync now"}
          busyLabel="Starting…"
          help={actionHelp.sync}
          disabled={syncing || sync.value === null}
          run={async () => {
            await postJSON("/admin/sync", { mode: "sync" });
            return after("Sync started.");
          }}
        />
        <Action
          label="Back up now"
          busyLabel="Backing up…"
          help={actionHelp.backup}
          run={async () => {
            const r = await postJSON<{ rows: Record<string, number> }>("/admin/backup", {});
            return after(`Backed up ${r.rows.query_log} questions and ${r.rows.planner_items ?? 0} planner items.`);
          }}
        />
        <Action
          label="Rescan inbox"
          busyLabel="Rescanning…"
          help={actionHelp.rescan}
          run={async () => after(`Rescanned: ${countsLine(await postJSON<Record<string, number>>("/ingest/rescan", {}))}.`)}
        />
        {enrich?.enabled && (
          <Action
            label={enrich.paused ? "Resume summaries" : "Pause summaries"}
            busyLabel={enrich.paused ? "Resuming…" : "Pausing…"}
            help={actionHelp.enrich}
            run={async () => {
              const e = await postJSON<EnrichmentStatus>(`/admin/enrich/${enrich.paused ? "resume" : "pause"}`, {});
              return after(e.paused ? "Summaries paused." : "Summaries resumed.");
            }}
          />
        )}
      </div>
      {syncing && (
        <p className="muted">
          A sync is running. <Link href="/admin/library#sync">See its progress</Link>
        </p>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Write GlanceTiles**

Create `frontend/components/admin/GlanceTiles.tsx`:

```tsx
"use client";

import { useAdminData } from "@/components/admin/AdminData";
import { age, gpuShareReading, indexReading, isBackupOld, isSyncOld, servicesReading } from "@/lib/readings";

type Tile = { label: string; value: string; reading: string | null; bad?: boolean };

/** Five readings, each with what it means. */
export function GlanceTiles() {
  const { status, sync, now } = useAdminData();
  const s = status.value;
  const y = sync.value;
  if (!s) return null;

  const svc = servicesReading(s.services);
  const llm = s.llm;
  const tiles: Tile[] = [
    { label: "Services", value: svc.ok ? "Ready" : "Down", reading: svc.text, bad: !svc.ok },
    {
      label: "Answer model",
      value: llm?.model ?? "Unknown",
      reading: !llm
        ? "Ollama isn't answering"
        : llm.loaded
          ? gpuShareReading(llm.gpu_share)
          : "not loaded: the next question loads it (about 10 s)",
    },
    { label: "Index", value: s.index ? `${s.index.documents.toLocaleString("en-GB")} files` : "–", reading: indexReading(s.index) },
    {
      label: "Last sync",
      value: y?.last_full_sync ? age(y.last_full_sync, now) : y ? "Never" : "–",
      reading: !y
        ? null
        : y.auto_days === 0
          ? "automatic sync off"
          : isSyncOld(y.last_full_sync, y.auto_days, now)
            ? "overdue"
            : `automatic every ${y.auto_days} days`,
      bad: !!y && y.auto_days > 0 && isSyncOld(y.last_full_sync, y.auto_days, now),
    },
    {
      label: "Last backup",
      value: s.backup ? age(s.backup.at, now) : "None",
      reading: isBackupOld(s.backup?.at ?? null, now) ? "older than 2 days" : `${s.backup!.kept} kept`,
      bad: isBackupOld(s.backup?.at ?? null, now),
    },
  ];

  return (
    <section className="glance" aria-label="At a glance">
      {tiles.map((t) => (
        <div key={t.label} className={`glance-tile${t.bad ? " bad" : ""}`}>
          <span className="glance-label">{t.label}</span>
          <span className="glance-value">{t.value}</span>
          {t.reading && <span className="glance-reading">{t.reading}</span>}
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 4: Write SystemDetails (StatusCard without the actions, reading from the provider)**

Create `frontend/components/admin/SystemDetails.tsx`:

```tsx
"use client";

import { useAdminData } from "@/components/admin/AdminData";
import { Explain } from "@/components/admin/Explain";
import type { AdminStatus, EnrichmentStatus } from "@/lib/api";
import { detailHelp } from "@/lib/adminHelp";
import { gpuShareReading, servicesReading, vramReading } from "@/lib/readings";
import { ago } from "@/lib/seen";

const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const mb = (bytes: number) => `${(bytes / 2 ** 20).toFixed(0)} MB`;

function llmLine(l: AdminStatus["llm"]): string {
  if (l === null) return "Unknown: Ollama isn't answering";
  if (!l.loaded) return `${l.model} · not loaded (the next question loads it, ~10 s)`;
  const until = l.expires_at
    ? ` · unloads ${new Date(l.expires_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
    : "";
  return `${l.model} · ${Math.round(l.gpu_share * 100)}% on the GPU${until}`;
}

function rerankerLine(r: AdminStatus["reranker"]): string {
  if (!r) return "Unknown";
  if (r.state === "ready") return "Ready on the GPU";
  if (r.state === "not loaded") return "Loads on the next question (a few seconds)";
  return `Off: ${r.reason}`;
}

function enrichLine(e: EnrichmentStatus): string {
  const c = e.counts;
  const parts = [`${c.ok}/${c.ok + c.error + c.pending} summarised`];
  if (c.error) parts.push(`${c.error} failed`);
  if (c.pending) parts.push(`${c.pending} to go`);
  if (e.state === "running" && e.current) parts.push(`summarising ${e.current}`);
  else if (e.state === "waiting") parts.push("waiting for a question or index job to finish");
  else if (e.state !== "idle" || c.pending) parts.push(e.state);
  return parts.join(" · ");
}

/** The full system reading: services, model, reranker, GPU, answer times, index and summaries. */
export function SystemDetails() {
  const { status } = useAdminData();
  const s = status.value;
  if (!s) return status.failed ? null : <p className="muted">Checking the cabinet…</p>;

  const svc = servicesReading(s.services);
  const gpu = s.gpu;
  return (
    <section className="admin-card" id="details" aria-labelledby="details-h">
      <h2 id="details-h">System details</h2>
      {status.failed && <p className="notice bad">Lost the backend. Showing the last reading.</p>}
      <dl className="kv">
        <dt>Services</dt>
        <dd className={svc.ok ? "ok" : "bad"}>{svc.text}</dd>

        <dt>LLM</dt>
        <dd>
          <span>{llmLine(s.llm)}</span>
          <Explain line={s.llm?.loaded ? gpuShareReading(s.llm.gpu_share) : null} more={detailHelp.llm} />
        </dd>

        <dt>Reranker</dt>
        <dd className={s.reranker?.state === "off" && s.reranker.reason !== "turned off in Settings" ? "bad" : ""}>
          <span>{rerankerLine(s.reranker)}</span>
          <Explain more={detailHelp.reranker} />
        </dd>

        <dt>GPU</dt>
        <dd>
          {gpu.available ? (
            <>
              <span>
                {gpu.name} · {gpu.used_mib} / {gpu.total_mib} MiB
              </span>
              <meter className="vram" min={0} max={gpu.total_mib} value={gpu.used_mib} high={gpu.total_mib * 0.9}>
                {Math.round((gpu.used_mib / gpu.total_mib) * 100)}%
              </meter>
              <Explain line={vramReading(gpu.used_mib, gpu.total_mib)} more={detailHelp.gpu} />
            </>
          ) : (
            "Unavailable (nvidia-smi not found)"
          )}
        </dd>

        <dt>Answers</dt>
        <dd>
          <span>
            {!s.answers
              ? "–"
              : s.answers.count === 0
                ? "No questions asked yet"
                : `Median ${secs(s.answers.median_ms)}, slowest ${secs(s.answers.max_ms)} over the last ${s.answers.count} · last asked ${ago(s.answers.last_at)}`}
          </span>
          <Explain more={detailHelp.answers} />
        </dd>

        <dt>Index</dt>
        <dd>
          <span>
            {s.index
              ? `${s.index.documents} documents · ${s.index.chunks} chunks · ${s.index.excluded} excluded · ${mb(s.index.db_bytes)} on disk · ${s.index.ocr.available ? `OCR on · ${s.index.ocr.pages} passages` : "OCR off: language data missing (python -m app.ingest.ocr --setup)"}`
              : "–"}
          </span>
          <Explain more={detailHelp.index} />
        </dd>

        <dt>Summaries</dt>
        <dd>
          <span>{s.enrichment ? enrichLine(s.enrichment) : "–"}</span>
          <Explain more={detailHelp.summaries} />
        </dd>
      </dl>
    </section>
  );
}
```

- [ ] **Step 5: Assemble the Overview and delete StatusCard**

Replace `frontend/app/admin/page.tsx`:

```tsx
import { ActionStrip } from "@/components/admin/ActionStrip";
import { GlanceTiles } from "@/components/admin/GlanceTiles";
import { NeedsAttention } from "@/components/admin/NeedsAttention";
import { SystemDetails } from "@/components/admin/SystemDetails";

export default function AdminOverview() {
  return (
    <>
      <NeedsAttention />
      <ActionStrip />
      <GlanceTiles />
      <SystemDetails />
    </>
  );
}
```

Run: `cd "C:/dev/Second Brain" && git rm frontend/components/admin/StatusCard.tsx && grep -rn "StatusCard" frontend/app frontend/components`
Expected: no matches.

- [ ] **Step 6: Reuse countsLine in LibraryAdmin**

In `frontend/components/admin/LibraryAdmin.tsx`, delete the local `const counts = …` block (the 4-line arrow function) and add `import { countsLine } from "@/lib/readings";`. Then replace the two calls `counts(s)` and `counts(await postJSON<…>("/admin/reindex", body))` with `countsLine(…)`.

- [ ] **Step 7: Style the Overview pieces**

Append to `frontend/app/globals.css` after the tab-bar block from Task 4:

```css
/* ---- admin overview: attention, actions, tiles ------------------------------------------ */
.attention-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.attention-item {
  border-left: 3px solid var(--rule-blue);
  padding: 0.3rem 0 0.3rem 0.7rem;
}

.attention-item.bad {
  border-left-color: var(--bad);
}

.attention-item.warn {
  border-left-color: var(--rule-red);
}

.attention-item a {
  color: var(--ink);
}

.action-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 1rem;
}

.action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
}

.glance {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0.75rem;
}

.glance-tile {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  background: var(--card);
  border-radius: 4px;
  box-shadow: var(--shadow);
  padding: 0.7rem 0.9rem;
}

.glance-label {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.glance-value {
  font-weight: 600;
}

.glance-reading {
  font-size: 0.8rem;
  color: var(--muted);
}

.glance-tile.bad .glance-reading {
  color: var(--bad);
}
```

- [ ] **Step 8: Check types, lint, tests and the build**

Run: `cd "C:/dev/Second Brain/frontend" && npx tsc --noEmit && npm run lint && npm test && npm run build`
Expected: no errors; all tests pass; the build succeeds.

- [ ] **Step 9: Check it in the browser**

With `backend` and `frontend` running from the main checkout, open `http://localhost:3000/admin` and check each item:
- Needs attention lists the same problems the badges count, or shows "Nothing needs you…".
- **Back up now** shows its note, and the Last backup tile changes to "just now" within 10 s.
- **Rescan inbox** shows "Rescanned: …".
- **Pause summaries** changes its label to Resume after the next poll. Resume it again afterwards.
- Every "How it works" disclosure opens.
- Clicking an attention item lands on the right card.
- The console has no errors.

Don't click **Sync now** unless the student asks: it logs into Blackboard.

- [ ] **Step 10: Commit**

```bash
cd "C:/dev/Second Brain" && git add -A frontend/app/admin frontend/components/admin frontend/app/globals.css && git commit -m "Admin Overview: needs attention, everyday actions, five tiles and system details (StatusCard split up)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Explanations in the existing cards

**Files:**
- Modify: `frontend/components/admin/SettingsCard.tsx`, `LibraryAdmin.tsx`, `TagsCard.tsx`, `SyncCard.tsx`, `InsightsCard.tsx`, `EvalCard.tsx`

**Interfaces:**
- Consumes: `Explain` (Task 3); `settingMore`, `actionHelp` and `metricHelp` (Task 3); `recallReading` (Task 1).
- Produces: no new exports.

- [ ] **Step 1: Settings: add "How it works" under each setting's help line**

In `SettingsCard.tsx`, add these imports:

```tsx
import { Explain } from "@/components/admin/Explain";
import { settingMore } from "@/lib/adminHelp";
```

Directly after `<span className="help">{r.locked_by ? `Set by ${r.locked_by}; change it there.` : r.help}</span>`, insert:

```tsx
                    <Explain more={settingMore[r.key]} />
```

- [ ] **Step 2: Library: explain Rescan, Re-index/Re-enrich and Exclude/Include**

In `LibraryAdmin.tsx`, add these imports:

```tsx
import { Explain } from "@/components/admin/Explain";
import { actionHelp } from "@/lib/adminHelp";
```

Directly after the closing `</header>` of the Library section, insert:

```tsx
      <Explain line={actionHelp.rescan.line} more={actionHelp.rescan.more} />
```

Directly after the closing `</table>` of the module table, insert:

```tsx
      <Explain line={actionHelp.reindex.line} more={actionHelp.reindex.more} />
      <Explain line={actionHelp.reenrich.line} more={actionHelp.reenrich.more} />
```

Directly after `<h3>Excluded</h3>`, insert:

```tsx
      <Explain line={actionHelp.exclude.line} more={actionHelp.exclude.more} />
```

- [ ] **Step 3: Tags and Sync: explain the vocabulary pass and Sync now**

In `TagsCard.tsx`, add the same two imports as Step 2. Directly after the closing `</header>`, insert:

```tsx
      <Explain line={actionHelp.vocab.line} more={actionHelp.vocab.more} />
```

In `SyncCard.tsx`, add the same two imports. Directly after the `<p className="muted">…</p>` that shows "Last full sync …", insert:

```tsx
      <Explain line={actionHelp.sync.line} more={actionHelp.sync.more} />
```

- [ ] **Step 4: Insights: explain refused and invalid citations**

In `InsightsCard.tsx`, add these imports:

```tsx
import { Explain } from "@/components/admin/Explain";
import { metricHelp } from "@/lib/adminHelp";
```

Change the Refused and Invalid citations `<dd>`s to:

```tsx
            <dt>Refused</dt>
            <dd>
              {s.refused} ({pct(s.refused, s.questions)}): not in your fiches
              <Explain more={metricHelp.refused} />
            </dd>
            <dt>Invalid citations</dt>
            <dd>
              {s.invalid} ({pct(s.invalid, s.questions)}){s.failed ? ` · ${s.failed} failed before answering` : ""}
              <Explain more={metricHelp.invalid} />
            </dd>
```

- [ ] **Step 5: Evaluation: define each measure and read recall@5 aloud**

In `EvalCard.tsx`, add these imports:

```tsx
import { Explain } from "@/components/admin/Explain";
import { metricHelp } from "@/lib/adminHelp";
import { recallReading } from "@/lib/readings";
```

In the measures table, change `<th scope="row">{r.label}</th>` to:

```tsx
                    <th scope="row">
                      {r.label}
                      <Explain more={metricHelp[r.key]} />
                    </th>
```

Directly after the closing `</table>` of that first table (before `{latest.metrics.answers && (`), insert:

```tsx
          {(() => {
            const m = latest.metrics.overall["dense+rerank"]?.["recall@5"] !== undefined ? MODES[2] : MODES[0];
            const r = recallReading(5, latest.metrics.overall[m.key]?.["recall@5"]);
            return r && <Explain line={`${m.label}: ${r}.`} />;
          })()}
```

In the Answers `<dl>`, append `<Explain more={metricHelp.citation_valid_rate} />` inside the "Citations valid" `<dd>` and `<Explain more={metricHelp.cited_right_rate} />` inside the "Cited the right page" `<dd>`, each after the existing `show(…)` expression.

- [ ] **Step 6: Check types, lint and tests**

Run: `cd "C:/dev/Second Brain/frontend" && npx tsc --noEmit && npm run lint && npm test`
Expected: no errors; all tests pass.

- [ ] **Step 7: Check it in the browser**

Open `/admin/library`, `/admin/quality` and `/admin/settings`, and check each item:
- Every setting has a "How it works" disclosure with the right text. Read three of them against `lib/adminHelp.ts`.
- The Library shows the Rescan, Re-index, Re-enrich and Exclude lines.
- The Evaluation shows the "Reranked: the right page is in the top 5 for N% of questions." line, or Dense when no reranked run exists.
- The console has no errors.

- [ ] **Step 8: Commit**

```bash
cd "C:/dev/Second Brain" && git add frontend/components/admin && git commit -m "Admin cards explain themselves: settings, library actions, tags, sync, insights and evaluation measures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Design pass with impeccable

**Files:**
- Modify: `frontend/app/globals.css` (the admin blocks added in Tasks 3–5), plus the markup of the new admin components if the pass calls for it
- Read: `DESIGN.md`, `PRODUCT.md`

**Interfaces:**
- Consumes: every component from Tasks 3–6.
- Produces: no new exports. Class names can change only if every use is updated.

- [ ] **Step 1: Run the impeccable skill**

Invoke the `impeccable` skill for a polish-and-critique pass. Scope it to the admin tab bar, the badge, the Needs-attention list, the action strip, the glance tiles and the `.explain` pattern. Constraints to give it:
- Use the existing DESIGN.md tokens and card-catalogue language only, with no new colours.
- Light and dark mode.
- Visible keyboard focus (`--focus`).
- A laptop width of about 1280 px is the primary target. Narrow widths must not scroll horizontally, and the tabs wrap.

- [ ] **Step 2: Apply its fixes, then check lint and the build**

Run: `cd "C:/dev/Second Brain/frontend" && npm run lint && npm run build`
Expected: both succeed.

- [ ] **Step 3: Check it in the browser in both themes**

For each of the four tabs, take a screenshot in light mode, then again with `resize_window` `colorScheme: "dark"`. Also check at 1280 px and 800 px widths. Tab through the tab bar and the actions to confirm the focus rings. Set the colour scheme back afterwards.

- [ ] **Step 4: Commit**

```bash
cd "C:/dev/Second Brain" && git add frontend && git commit -m "Admin design pass: tab bar, attention list, actions, tiles and explanations in the card-catalogue style

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: README and final verification

**Files:**
- Modify: `README.md` (the `## Admin panel` section)

- [ ] **Step 1: Rewrite the Admin panel section**

Replace the bullets under `## Admin panel` in `README.md` with:

```markdown
Click the status line at the foot of the rail ("Ready · qwen3:4b-instruct") to open `/admin`. It has four tabs; a red number on a tab counts the problems waiting there.
- **Overview:** what needs attention (services down, a Blackboard login or failed sync, a sync or backup that's overdue, files that couldn't be read, and too many invalid citations or refusals in the last 7 days), each linked to where it's fixed. Then the everyday actions (**Sync now**, **Back up now**, **Rescan inbox**, **Pause summaries**), five at-a-glance tiles, and the system details: model and GPU share, reranker, VRAM, answer times, index, OCR and summaries.
- **Library:** counts per module, files that couldn't be read, **Re-index**, **Re-enrich**, **Exclude** and **Include**; tags and the vocabulary pass; and the Blackboard sync. See Syncing from Blackboard below.
- **Quality:** insights over 7 days, 30 days or all time (questions, refusals, invalid citations, answer times, the trend, per module, the problem questions, dense vs hybrid), and the evaluation. See Evaluation below.
- **Settings:** retrieval and answer settings, saved to `config.local.yaml`, applied from the next question with no restart. See Configuration below.

Every setting, measure and action says what it does, with a "How it works" note for the details.
```

- [ ] **Step 2: Run the full check**

Run: `cd "C:/dev/Second Brain/frontend" && npm test && npm run lint && npm run build`
Expected: all pass. Paste the test summary line (`# pass N`, `# fail 0`) into the hand-off.

- [ ] **Step 3: Commit**

```bash
cd "C:/dev/Second Brain" && git add README.md && git commit -m "README: the admin panel in four tabs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Finish the branch**

Invoke `superpowers:finishing-a-development-branch` so the student can choose between merging `admin-tabs` into `main` and opening a PR.
