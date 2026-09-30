// Run with: npm test (node's own runner; no framework needed for pure string logic)
import assert from "node:assert/strict";
import { test } from "node:test";
import { appendClip, clipBlock, pickScratch, scratchTitle } from "./scratchpad.ts";

test("scratchTitle names the drawer, or none for all drawers", () => {
  assert.equal(scratchTitle("Probability 2"), "Scratchpad · Probability 2");
  assert.equal(scratchTitle(null), "Scratchpad");
});

test("clipBlock quotes every line and credits its sources", () => {
  assert.equal(
    clipBlock("B_0 = 0.\nIncrements are independent.", ["PROB2 · CH1 · p. 17", "PROB2 · CH1"]),
    "> B_0 = 0.\n> Increments are independent.\n>\n> — PROB2 · CH1 · p. 17; PROB2 · CH1",
  );
});

test("clipBlock keeps blank lines inside the quote and trims the ends", () => {
  assert.equal(clipBlock("\n  one\n\ntwo  \n", ["S"]), "> one\n>\n> two\n>\n> — S");
});

test("clipBlock without sources is a bare quote", () => {
  assert.equal(clipBlock("just this", []), "> just this");
});

test("clipBlock drops duplicate sources", () => {
  assert.equal(clipBlock("x", ["A", "A", "B"]), "> x\n>\n> — A; B");
});

test("appendClip separates clips by a blank line", () => {
  assert.equal(appendClip("", "> a"), "> a\n");
  assert.equal(appendClip("my note", "> a"), "my note\n\n> a\n");
  assert.equal(appendClip("my note\n\n\n", "> a"), "my note\n\n> a\n");
});

const note = (o: Partial<{ id: number; title: string; course: string | null; kind: string; filed_path: string | null }>) => ({
  id: 1,
  title: "Scratchpad · CSR",
  course: "CSR",
  kind: "note",
  filed_path: null,
  ...o,
});

test("pickScratch finds the drawer's unfiled scratchpad", () => {
  const items = [
    note({ id: 1, filed_path: "CSR/notes/old.md" }),
    note({ id: 2, title: "Something else" }),
    note({ id: 3, kind: "todo" }),
    note({ id: 4, course: "DEVOPS", title: "Scratchpad · CSR" }),
    note({ id: 5 }),
  ];
  assert.equal(pickScratch(items, "CSR")?.id, 5);
  assert.equal(pickScratch(items, "SDG"), null);
});

test("pickScratch for all drawers only takes a note with no course", () => {
  const items = [note({ id: 1, title: "Scratchpad", course: "CSR" }), note({ id: 2, title: "Scratchpad", course: null })];
  assert.equal(pickScratch(items, null)?.id, 2);
});
