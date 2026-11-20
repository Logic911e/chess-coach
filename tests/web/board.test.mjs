import { test } from "node:test";
import assert from "node:assert/strict";
import { parseFen, squareXY, moveArrows, keyIndex, startIndex, clampIndex } from "../../src/chess_coach/web/js/board.js";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const colors = { best: "#2e9d5b", mistake: "#e07a1f" };

test("test_parse_fen_start_position", () => {
  const g = parseFen(START);
  assert.equal(g.length, 8);
  assert.equal(g[0].join(""), "rnbqkbnr");
  assert.equal(g[7].join(""), "RNBQKBNR");
  assert.deepEqual(g[3], Array(8).fill(null));
});

test("parse_fen_expands_digit_runs", () => {
  assert.deepEqual(parseFen("4k3/8/8/8/8/8/8/R3K2R w - - 0 1")[7], ["R", null, null, null, "K", null, null, "R"]);
});

test("test_square_xy_flipped", () => {
  assert.deepEqual(squareXY("a1", false), [0.5, 7.5]);
  assert.deepEqual(squareXY("a1", true), [7.5, 0.5]);
  assert.deepEqual(squareXY("h8", false), [7.5, 0.5]);
});

test("test_arrow_of_same_move_is_deduplicated", () => {
  const mv = { uci: "e2e4", best_uci: "e2e4", classification: "best" };
  assert.deepEqual(moveArrows(mv, colors), [{ uci: "e2e4", color: "#2e9d5b" }]);
});

test("arrows_for_a_mistake_are_played_then_best", () => {
  const mv = { uci: "b1c3", best_uci: "e2e4", classification: "mistake" };
  assert.deepEqual(moveArrows(mv, colors), [
    { uci: "b1c3", color: "#e07a1f" }, { uci: "e2e4", color: "#2e9d5b" }]);
});

test("guess_mode_hides_the_engine_arrow", () => {
  const mv = { uci: "b1c3", best_uci: "e2e4", classification: "mistake" };
  assert.deepEqual(moveArrows(mv, colors, { hideBest: true }), [{ uci: "b1c3", color: "#e07a1f" }]);
});

const mk = (keys) => keys.map((k) => ({ is_key_moment: k }));

test("test_game_without_key_moments_still_renders_first_move", () => {
  const moves = mk([false, false, false]);
  assert.equal(startIndex(moves), 0);
  assert.equal(keyIndex(moves, 0, 1), -1);
  assert.equal(keyIndex(moves, 2, -1), -1);
});

test("key_moment_navigation_both_directions", () => {
  const moves = mk([false, true, false, true, false]);
  assert.equal(startIndex(moves), 1);
  assert.equal(keyIndex(moves, 1, 1), 3);
  assert.equal(keyIndex(moves, 3, 1), -1);
  assert.equal(keyIndex(moves, 3, -1), 1);
  assert.equal(keyIndex(moves, 1, -1), -1);
});

test("empty_game_is_safe", () => {
  assert.equal(startIndex([]), 0);
  assert.equal(keyIndex([], 0, 1), -1);
});

test("clamp_index_never_goes_negative_on_an_empty_game", () => {
  assert.equal(clampIndex([], 5), 0);
  assert.equal(clampIndex([], -3), 0);
  assert.equal(clampIndex(mk([false, false]), 9), 1);
});

import { pieceSlides } from "../../src/chess_coach/web/js/board.js";
const AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1";

test("test_piece_slides_simple_move_both_directions", () => {
  assert.deepEqual(pieceSlides(START, AFTER_E4), [{ from: "e2", to: "e4" }]);
  assert.deepEqual(pieceSlides(AFTER_E4, START), [{ from: "e4", to: "e2" }]);
});

test("test_piece_slides_capture_and_castling", () => {
  // white bishop takes a black pawn: only the bishop slides
  assert.deepEqual(pieceSlides("4k3/8/8/3p4/8/1B6/8/4K3 w - - 0 1", "4k3/8/8/3B4/8/8/8/4K3 b - - 0 1")
    .map((s) => s.to + s.from), ["d5b3"]);
  // kingside castling: king and rook both slide
  const s = pieceSlides("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "4k3/8/8/8/8/8/8/5RK1 b - - 1 1");
  assert.deepEqual(s.map((x) => x.from + x.to).sort(), ["e1g1", "h1f1"]);
});

test("test_piece_slides_nothing_when_unmatched_or_same", () => {
  assert.deepEqual(pieceSlides(START, START), []);
  // promotion: the pawn disappears and a queen appears; no match, no slide
  assert.deepEqual(pieceSlides("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "Q3k3/8/8/8/8/8/8/4K3 b - - 0 1"), []);
});
