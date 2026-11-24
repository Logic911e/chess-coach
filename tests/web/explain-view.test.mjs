import { test } from "node:test";
import assert from "node:assert/strict";
import { explainBlocks, fieldsNote } from "../../src/chess_coach/web/js/explain-view.js";

const FIELDS = [
  { key: "verdict", label: "Verdict", text: "Black's Nf6 is a blunder.", source: "code" },
  { key: "reason", label: "Why", text: "The f7 pawn was already under threat.", source: "model" },
  { key: "better", label: "What was better", text: "Black should have played g6.", source: "facts" },
];

test("fields give one block each, with the verdict unlabelled", () => {
  const b = explainBlocks(FIELDS, "ignored");
  assert.deepEqual(b.map((x) => x.key), ["verdict", "reason", "better"]);
  assert.equal(b[0].label, "");
  assert.equal(b[1].label, "Why");
  assert.equal(b[2].label, "What was better");
});

test("an explanation without fields is one block of its text, and nothing is a no-op", () => {
  assert.deepEqual(explainBlocks(null, "Plain text."), [{ key: "text", label: "", text: "Plain text." }]);
  assert.deepEqual(explainBlocks([], "Plain text."), [{ key: "text", label: "", text: "Plain text." }]);
  assert.deepEqual(explainBlocks(null, ""), []);
});

test("empty or malformed fields are skipped", () => {
  const b = explainBlocks([null, { key: "reason", label: "Why", text: "" }, FIELDS[1]], "x");
  assert.deepEqual(b.map((x) => x.key), ["reason"]);
});

test("the note names the parts written from the facts, and is empty when none were", () => {
  assert.match(fieldsNote(FIELDS), /what was better was written straight from the engine facts/);
  assert.equal(fieldsNote([FIELDS[0], FIELDS[1]]), "");
  assert.equal(fieldsNote(null), "");
  const two = fieldsNote([{ key: "reason", label: "Why", text: "a", source: "facts" }, FIELDS[2]]);
  assert.match(two, /why and what was better were written/);
});
