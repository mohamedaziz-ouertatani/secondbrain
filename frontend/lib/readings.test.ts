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
