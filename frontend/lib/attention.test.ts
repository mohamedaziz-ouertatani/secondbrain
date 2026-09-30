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
