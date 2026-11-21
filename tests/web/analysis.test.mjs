import { test } from "node:test";
import assert from "node:assert/strict";
import {
  scoreFromStored, formatScore, barFill, barLabel, lineText, lineA11yName,
} from "../../src/chess_coach/web/js/analysis.js";

const cp = (n) => ({ cp: n, mate: null });
const mate = (n) => ({ cp: null, mate: n });
const FEN_W = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 11";
const FEN_B = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/1PPBPN2/P2N1PPP/R2QK2R b KQ - 0 11";
const mv = (...sans) => sans.map((san) => ({ san, uci: "", fen: "", capture: false, check: false }));

test("test_score_from_stored_flips_for_black_mover", () => {
  assert.deepEqual(scoreFromStored(120, "white"), { cp: 120, mate: null, capped: false });
  assert.deepEqual(scoreFromStored(120, "black"), { cp: -120, mate: null, capped: false });
  assert.equal(scoreFromStored(0, "black").cp, 0);
  assert.ok(!Object.is(scoreFromStored(0, "black").cp, -0));
});

test("test_stored_mate_cap_is_flagged", () => {
  assert.equal(scoreFromStored(10000, "white").capped, true);
  assert.equal(scoreFromStored(10000, "black").cp, -10000);
  assert.equal(scoreFromStored(-9000, "white").capped, true);
  assert.equal(scoreFromStored(8999, "white").capped, false);
  assert.equal(formatScore(scoreFromStored(10000, "white")), "Mate");
  assert.equal(barLabel(scoreFromStored(-10000, "white")), "Mate");
});

test("test_format_score_pawns_signs_and_mate", () => {
  assert.equal(formatScore(cp(20)), "+0.20");
  assert.equal(formatScore(cp(-123)), "-1.23");
  assert.equal(formatScore(cp(0)), "0.00");
  assert.equal(formatScore(cp(0.5)), "+0.01");
  assert.equal(formatScore(cp(-0.4)), "0.00");
  assert.equal(formatScore(cp(-0.2)), "0.00");
  assert.equal(formatScore(mate(3)), "M3");
  assert.equal(formatScore(mate(-3)), "-M3");
  assert.equal(formatScore(cp(40), 1), "+0.4");
});

test("test_bar_fill_is_monotonic_symmetric_and_clamped", () => {
  assert.equal(barFill(cp(0)), 0.5);
  let prev = -1;
  for (const x of [-3000, -800, -300, -100, -20, 0, 20, 100, 300, 800, 3000]) {
    const f = barFill(cp(x));
    assert.ok(f >= prev && f >= 0.02 && f <= 0.98);
    prev = f;
  }
  for (const x of [10, 50, 100, 250, 600]) {
    assert.ok(Math.abs(barFill(cp(x)) + barFill(cp(-x)) - 1) < 1e-12);
  }
  assert.ok(barFill(cp(100)) - 0.5 > 0.05);
  assert.equal(barFill(cp(100000)), 0.98);
  assert.equal(barFill(mate(2)), 0.98);
  assert.equal(barFill(mate(-2)), 0.02);
  assert.equal(barFill(scoreFromStored(10000, "black")), 0.02);
});

test("test_bar_label_one_decimal", () => {
  assert.equal(barLabel(cp(40)), "+0.4");
  assert.equal(barLabel(cp(-125)), "-1.3");
  assert.equal(barLabel(cp(0)), "0.0");
  assert.equal(barLabel(mate(3)), "M3");
});

test("test_line_text_numbers_moves_from_the_fen_and_truncates", () => {
  assert.equal(lineText(FEN_W, mv("b3", "Re8", "Be3")), "11. b3 Re8 12. Be3");
  const long = mv("a", "b", "c", "d", "e", "f", "g", "h", "i", "j");
  assert.equal(lineText(FEN_W, long), "11. a b 12. c d 13. e f 14. g h ...");
  assert.equal(lineText(FEN_W, long, 3), "11. a b 12. c ...");
  assert.equal(lineText(FEN_W, []), "");
  assert.equal(lineText("junk", mv("e4")), "1. e4");
});

test("test_line_text_black_to_move_starts_with_ellipsis_number", () => {
  assert.equal(lineText(FEN_B, mv("Re8", "Be3", "a5")), "11... Re8 12. Be3 a5");
});

test("test_line_a11y_name", () => {
  assert.equal(lineA11yName(1, cp(40), "11. b3 Re8 ..."), "Line 1, plus 0.40, 11. b3 Re8 ...");
  assert.equal(lineA11yName(2, cp(-123), "x"), "Line 2, minus 1.23, x");
  assert.equal(lineA11yName(1, mate(3), "x"), "Line 1, mate in 3 for White, x");
  assert.equal(lineA11yName(3, mate(-3), "x"), "Line 3, mate in 3 for Black, x");
});

const JUNK = [NaN, undefined, null, Infinity, -Infinity, "40", {}];

test("test_junk_cp_and_missing_score_read_as_level", () => {
  const scores = [...JUNK.map((v) => ({ cp: v, mate: null })), { mate: null }, {}, null, undefined];
  for (const sc of scores) {
    assert.equal(formatScore(sc), "0.00");
    assert.equal(formatScore(sc, 1), "0.0");
    assert.equal(barLabel(sc), "0.0");
    assert.equal(barFill(sc), 0.5);
  }
  for (const v of JUNK) {
    assert.deepEqual(scoreFromStored(v, "white"), { cp: 0, mate: null, capped: false });
    assert.deepEqual(scoreFromStored(v, "black"), { cp: 0, mate: null, capped: false });
  }
});

test("test_bar_fill_always_finite_and_clamped", () => {
  for (const sc of [cp(NaN), cp(1e12), cp(-1e12), mate(NaN), mate(0), mate(5), null, { cp: "x" }]) {
    const f = barFill(sc);
    assert.ok(Number.isFinite(f) && f >= 0.02 && f <= 0.98);
  }
});

test("test_mate_zero_reads_mate_without_number", () => {
  assert.equal(formatScore(mate(0)), "Mate");
  assert.equal(barLabel(mate(0)), "Mate");
  assert.equal(lineA11yName(1, mate(0), "x"), "Line 1, mate, x");
  assert.equal(lineA11yName(1, { cp: -500, mate: 0 }, "x"), "Line 1, mate for Black, x");
  assert.equal(barFill({ cp: -500, mate: 0 }), 0.02);
});

test("test_line_a11y_name_capped_mate_and_zero_score", () => {
  assert.equal(lineA11yName(1, scoreFromStored(10000, "white"), "x"), "Line 1, mate for White, x");
  assert.equal(lineA11yName(2, scoreFromStored(10000, "black"), "x"), "Line 2, mate for Black, x");
  assert.equal(lineA11yName(1, cp(0), "x"), "Line 1, 0.00, x");
  assert.equal(lineA11yName(1, null, "x"), "Line 1, 0.00, x");
});

test("test_line_text_truncates_with_black_to_move_first", () => {
  const long = mv("a", "b", "c", "d", "e", "f");
  assert.equal(lineText(FEN_B, long, 4), "11... a 12. b c 13. d ...");
  assert.equal(lineText(FEN_B, long, 6), "11... a 12. b c 13. d e 14. f");
});
