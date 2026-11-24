import test from "node:test";
import assert from "node:assert/strict";

// accounts.js touches `document` only inside mountAccounts, so the pure helper can be imported alone.
const { syncText } = await import("../../src/chess_coach/web/js/accounts.js");

test("syncText describes each state", () => {
  assert.equal(syncText({ state: "idle" }), "");
  assert.equal(syncText({ state: "fetching" }), "Fetching games…");
  assert.equal(syncText({ state: "analysing", done: 3, total: 40 }), "Analysing 3 of 40");
  assert.equal(syncText({ state: "done", imported: 12, message: "2 already stored" }), "Synced: 12 new, 2 already stored.");
  assert.equal(syncText({ state: "done", imported: 0, message: "" }), "Synced: 0 new.");
  assert.match(syncText({ state: "error", message: "could not reach lichess.org" }), /could not reach/);
});
