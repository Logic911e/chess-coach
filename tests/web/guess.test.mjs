import { test } from "node:test";
import assert from "node:assert/strict";
import { canGuess, createGuessFlow, revealLine, guessView, mayWriteExplain } from "../../src/chess_coach/web/js/guess.js";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const game = { white: "Alice", black: "Bob" };
const mv = (o = {}) => ({ id: 7, color: "white", is_key_moment: true, fen_before: START, ...o });
const ok = (o = {}) => ({ legal: true, matched: false, classification: "good", expected_points_lost: 0.01,
  san: "Nf3", best_san: "b3", ...o });

function setup(responses) {
  const sent = [], calls = [];
  const queue = [...responses];
  const api = { guessMove: async (id, uci) => { sent.push([id, uci]); const r = queue.shift(); if (r instanceof Error) throw r; return r; } };
  const rec = (name) => (...a) => calls.push([name, ...a]);
  const ui = { enter: rec("enter"), select: rec("select"), pending: rec("pending"), message: rec("message"),
    reveal: rec("reveal"), cancelled: rec("cancelled"), spentAlready: rec("spentAlready") };
  return { flow: createGuessFlow({ api, ui }), sent, calls };
}

test("test_can_guess_only_own_key_moments", () => {
  assert.equal(canGuess(mv(), "Alice", game), true);
  assert.equal(canGuess(mv({ color: "black" }), "Alice", game), false);
  assert.equal(canGuess(mv({ color: "black" }), "Bob", game), true);
  assert.equal(canGuess(mv({ is_key_moment: false }), "Alice", game), false);
  assert.equal(canGuess(mv(), null, game), false);
  assert.equal(canGuess(mv(), "alice", game), false);
  assert.equal(canGuess(mv(), "Alice", null), false);
});

test("test_illegal_guess_does_not_spend_the_attempt", async () => {
  const { flow, sent, calls } = setup([{ legal: false, matched: false, classification: null,
    expected_points_lost: null, san: null, best_san: "b3" }, ok()]);
  const m = mv();
  flow.begin(m);
  await flow.pick("e2"); await flow.pick("e5");
  assert.equal(calls.some((c) => c[0] === "reveal"), false);
  assert.equal(flow.active(), true);
  await flow.pick("g1"); await flow.pick("f3");
  assert.deepEqual(sent, [[7, "e2e5"], [7, "g1f3"]]);
  assert.equal(calls.filter((c) => c[0] === "reveal").length, 1);
});

test("test_second_legal_guess_is_ignored_after_reveal", async () => {
  const { flow, sent, calls } = setup([ok(), ok()]);
  const m = mv();
  flow.begin(m);
  await flow.pick("g1"); await flow.pick("f3");
  assert.equal(flow.active(), false);
  assert.equal(flow.begin(m), false);
  await flow.pick("e2"); await flow.pick("e4");
  assert.equal(sent.length, 1);
  assert.equal(flow.resultFor(m), "Your guess: Nf3, a good move, lost 0.01. Engine: b3");
  assert.equal(calls.filter((c) => c[0] === "reveal").length, 1);
});

test("test_promotion_pick_appends_queen_letter", async () => {
  const { flow, sent } = setup([ok(), ok()]);
  flow.begin(mv({ fen_before: "8/4P3/8/8/8/8/8/k6K w - - 0 1" }));
  await flow.pick("e7"); await flow.pick("e8");
  assert.deepEqual(sent[0], [7, "e7e8q"]);
  const b = mv({ id: 8, color: "black", fen_before: "k6K/8/8/8/8/8/4p3/8 b - - 0 1" });
  const t2 = setup([ok()]);
  t2.flow.begin(b);
  await t2.flow.pick("e2"); await t2.flow.pick("e1");
  assert.deepEqual(t2.sent[0], [8, "e2e1q"]);
  const t3 = setup([ok()]);   // a pawn moving to a non-last rank, and a non-pawn to rank 8, get no letter
  t3.flow.begin(mv({ fen_before: "4R3/4P3/8/8/8/8/8/k6K w - - 0 1" }));
  await t3.flow.pick("e8"); await t3.flow.pick("e7");
  assert.equal(t3.sent[0][1], "e8e7");
});

test("test_reveal_line_text", () => {
  assert.equal(revealLine(ok()), "Your guess: Nf3, a good move, lost 0.01. Engine: b3");
  assert.equal(revealLine(ok({ matched: true, classification: "best", expected_points_lost: 0 })),
    "Your guess: Nf3 matched the engine's move.");
  assert.equal(revealLine(ok({ classification: "blunder", expected_points_lost: 0.4321, san: "Qh5" })),
    "Your guess: Qh5, a blunder, lost 0.43. Engine: b3");
});

test("cancel_or_leaving_discards_a_late_answer", async () => {
  let release;
  const api = { guessMove: () => new Promise((r) => { release = r; }) };
  const calls = [];
  const ui = new Proxy({}, { get: (_, n) => (...a) => calls.push([n, ...a]) });
  const flow = createGuessFlow({ api, ui });
  flow.begin(mv());
  await flow.pick("g1");
  const p = flow.pick("f3");
  flow.cancel();
  release(ok());
  await p;
  assert.equal(calls.some((c) => c[0] === "reveal"), false);
  assert.equal(flow.resultFor(mv()), null);
  assert.equal(flow.active(), false);
});

test("test_failed_request_keeps_the_attempt_open", async () => {
  const { flow, calls } = setup([new Error("engine unavailable"), ok()]);
  flow.begin(mv());
  await flow.pick("g1"); await flow.pick("f3");
  assert.equal(flow.active(), true);
  assert.deepEqual(calls.filter((c) => c[0] === "message").pop().slice(1, 2), ["engine unavailable"]);
  await flow.pick("g1"); await flow.pick("f3");
  assert.equal(flow.active(), false);
});

test("picking_the_same_square_again_unselects_it", async () => {
  const { flow, sent } = setup([ok()]);
  flow.begin(mv());
  await flow.pick("g1"); await flow.pick("g1");
  assert.equal(sent.length, 0);
  await flow.pick("g1"); await flow.pick("f3");
  assert.equal(sent.length, 1);
});

test("reveal_line_articles_and_fallback", () => {
  const r = (classification) => revealLine({ matched: false, classification, san: "Qh5", best_san: "b3", expected_points_lost: 0.1 });
  assert.match(r("mistake"), /, a mistake, /);
  assert.match(r("inaccuracy"), /, an inaccuracy, /);
  assert.match(r("brilliant"), /, a brilliant move, /);
  assert.match(r("dubious"), /, a dubious move, /);
});

test("guess_view_hides_quality_while_guessing", () => {
  const m = { move_number: 12, color: "black", san: "Qh5", classification: "blunder" };
  const g = guessView(m, true);
  assert.equal(g.heading, "Move 12 · your move");
  assert.equal(g.showPill, false); assert.equal(g.showReasons, false);
  assert.equal(g.stripNeutral, true); assert.equal(g.stripTitle, "your move");
  for (const v of Object.values(g)) assert.doesNotMatch(String(v), /Qh5|blunder/);
  const n = guessView(m, false);
  assert.equal(n.heading, "12... Qh5"); assert.equal(n.showPill, true); assert.equal(n.showReasons, true);
  assert.equal(n.stripNeutral, false); assert.equal(n.stripTitle, "12... Qh5 (blunder)");
});

test("explain_may_write_only_outside_a_guess", () => {
  assert.equal(mayWriteExplain(true), false);
  assert.equal(mayWriteExplain(false), true);
});
