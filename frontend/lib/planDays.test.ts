// Run with: npm test (node's own runner). Dates are built local, so these hold in any time zone.
import assert from "node:assert/strict";
import { test } from "node:test";
import { daysOf } from "./planDays.ts";

const at = (y: number, m: number, d: number, h = 0, min = 0) => new Date(y, m - 1, d, h, min).toISOString();

test("an item without an end sits on its start day", () => {
  assert.deepEqual(daysOf({ starts_at: at(2026, 10, 15), ends_at: null }), ["2026-10-15"]);
  assert.deepEqual(daysOf({ starts_at: at(2026, 10, 15, 23, 59), ends_at: null }), ["2026-10-15"]);
});

test("an all-day span covers every day up to its exclusive end", () => {
  assert.deepEqual(daysOf({ starts_at: at(2026, 12, 30), ends_at: at(2027, 1, 2) }), [
    "2026-12-30",
    "2026-12-31",
    "2027-01-01",
  ]);
});

test("a timed event past midnight shows on both days; one ending at midnight doesn't", () => {
  assert.deepEqual(daysOf({ starts_at: at(2026, 10, 3, 22), ends_at: at(2026, 10, 4, 2) }), ["2026-10-03", "2026-10-04"]);
  assert.deepEqual(daysOf({ starts_at: at(2026, 10, 3, 22), ends_at: at(2026, 10, 4) }), ["2026-10-03"]);
  assert.deepEqual(daysOf({ starts_at: at(2026, 10, 3, 9), ends_at: at(2026, 10, 3, 9) }), ["2026-10-03"]);
});

test("a span is capped so a typo can't fill years", () => {
  assert.equal(daysOf({ starts_at: at(2026, 1, 1), ends_at: at(2036, 1, 1) }).length, 366);
});

test("undated items sit nowhere", () => {
  assert.deepEqual(daysOf({ starts_at: null, ends_at: null }), []);
});
