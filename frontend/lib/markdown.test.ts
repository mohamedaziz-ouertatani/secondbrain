// Run with: npm test (node's own runner)
import assert from "node:assert/strict";
import { test } from "node:test";
import { excerpt, relativeImagePath } from "./markdown.ts";

test("a note's image path is encoded once; anything with a scheme is not a file beside the note", () => {
  assert.equal(relativeImagePath("Serie 1/fig 1.png"), "Serie%201/fig%201.png");
  assert.equal(relativeImagePath("Serie%201/fig.png"), "Serie%201/fig.png");
  assert.equal(relativeImagePath("https://example.com/a.png"), null);
  assert.equal(relativeImagePath("javascript:alert(1)"), null);
  assert.equal(relativeImagePath("//evil.example/a.png"), null);
});

test("excerpts leave images out", () => {
  assert.equal(excerpt("Before ![fig 1.png](<Serie 1/fig 1.png>) after ![x](y.png)"), "Before after");
});
