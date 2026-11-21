import { test } from "node:test";
import assert from "node:assert/strict";
import { createExplore } from "../../src/chess_coach/web/js/explore.js";

const mv = (n) => ({ san: "m" + n, uci: "a1a2", fen: "fen" + n, capture: false, check: false });
const line = (...ns) => ns.map(mv);

test("test_begin_shows_first_move_position", () => {
  const e = createExplore();
  e.begin(line(1, 2, 3));
  assert.equal(e.active(), true);
  assert.equal(e.atStart(), true);
  const p = e.position();
  assert.equal(p.fen, "fen1");
  assert.equal(p.step, 0);
  assert.equal(p.move.san, "m1");
  assert.equal(e.path().length, 3);
});

test("test_step_forward_and_back_through_the_path", () => {
  const e = createExplore();
  e.begin(line(1, 2, 3));
  assert.equal(e.step(1).moved, true);
  assert.equal(e.position().fen, "fen2");
  assert.equal(e.atStart(), false);
  e.step(1);
  assert.equal(e.position().fen, "fen3");
  assert.equal(e.step(-1).moved, true);
  assert.equal(e.position().fen, "fen2");
});

test("test_step_back_from_the_first_position_exits", () => {
  const e = createExplore();
  e.begin(line(1, 2));
  assert.deepEqual(e.step(-1), { exited: true });
  assert.equal(e.active(), false);
  assert.equal(e.position(), null);
});

test("test_step_forward_at_end_is_noop", () => {
  const e = createExplore();
  e.begin(line(1, 2));
  e.step(1);
  assert.equal(e.step(1), null);
  assert.equal(e.position().fen, "fen2");
  assert.equal(e.active(), true);
});

test("test_extend_from_middle_truncates_and_appends", () => {
  const e = createExplore();
  e.begin(line(1, 2, 3, 4));
  e.step(1);  // at fen2
  e.extend(line(7, 8, 9));
  assert.deepEqual(e.path().map((m) => m.fen), ["fen1", "fen2", "fen7", "fen8", "fen9"]);
  assert.equal(e.position().fen, "fen7");
  assert.equal(e.position().step, 2);
  e.step(-1); e.step(-1);  // back to fen1: Left still walks all the way back
  assert.equal(e.position().fen, "fen1");
  assert.deepEqual(e.step(-1), { exited: true });
});

test("test_extend_at_the_end_appends", () => {
  const e = createExplore();
  e.begin(line(1, 2));
  e.step(1);
  e.extend(line(5, 6));
  assert.deepEqual(e.path().map((m) => m.fen), ["fen1", "fen2", "fen5", "fen6"]);
  assert.equal(e.position().fen, "fen5");
});

test("test_exit_clears_everything", () => {
  const e = createExplore();
  e.begin(line(1, 2));
  e.exit();
  assert.equal(e.active(), false);
  assert.deepEqual(e.path(), []);
  assert.equal(e.position(), null);
  assert.equal(e.step(1), null);
  assert.equal(e.atStart(), false);
});

test("test_position_is_null_when_not_exploring", () => {
  const e = createExplore();
  assert.equal(e.position(), null);
  assert.equal(e.active(), false);
  e.begin([]);  // an empty line explores nothing
  assert.equal(e.active(), false);
  e.extend(line(1));  // nothing to extend
  assert.equal(e.active(), false);
});
