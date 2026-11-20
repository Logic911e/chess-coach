import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveMe } from "../../src/chess_coach/web/js/me.js";

const players = [{ name: "Alice", games: 5 }, { name: "Bob", games: 3 }];

test("resolve me prefers stored name, then suggested, then prompt", () => {
  assert.deepEqual(resolveMe({ stored: "Bob", players, suggested: "Alice" }), { me: "Bob", needsPrompt: false });
  assert.deepEqual(resolveMe({ stored: null, players, suggested: "Alice" }), { me: "Alice", needsPrompt: false });
  assert.deepEqual(resolveMe({ stored: null, players, suggested: null }), { me: null, needsPrompt: true });
});

test("resolve me ignores stored name not in players", () => {
  assert.deepEqual(resolveMe({ stored: "Zed", players, suggested: null }), { me: null, needsPrompt: true });
  assert.deepEqual(resolveMe({ stored: "Zed", players, suggested: "Alice" }), { me: "Alice", needsPrompt: false });
});

test("resolve me with no players never prompts", () => {
  assert.deepEqual(resolveMe({ stored: "Zed", players: [], suggested: null }), { me: null, needsPrompt: false });
  assert.deepEqual(resolveMe({ stored: null, players: undefined, suggested: null }), { me: null, needsPrompt: false });
});

test("resolve me ignores a suggested name that is not among the players", () => {
  assert.deepEqual(resolveMe({ stored: null, players, suggested: "Ghost" }), { me: null, needsPrompt: true });
});
