import { test } from "node:test";
import assert from "node:assert/strict";
import {
  pathCrossesHidden, shouldExitExplore, isHiddenTarget, focusTarget, linePlyCounts, hiddenPositionKeys, positionKey,
} from "../../src/chess_coach/web/js/analysis-ui.js";

const F1 = "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 2";  // the key position
const F2 = "r1bqkbnr/pppp1ppp/2n5/8/3pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 3";
const F3 = "r1bqkbnr/pppp1ppp/2n5/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 3";
const F4 = "r1bqkb1r/pppp1ppp/2n2n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 1 4";
const ply = (fen) => ({ san: "x", uci: "a1a2", fen });
const keys = (...fens) => new Set(fens.map(positionKey));

test("pathCrossesHidden: passing through a hidden position at an inner ply is true", () => {
  assert.equal(pathCrossesHidden([ply(F2), ply(F3), ply(F4)], keys(F3)), true);
  assert.equal(pathCrossesHidden([ply(F3), ply(F2)], keys(F3)), true);
});

test("pathCrossesHidden: ending at the hidden position is allowed", () => {
  assert.equal(pathCrossesHidden([ply(F2), ply(F3)], keys(F3)), false);
  assert.equal(pathCrossesHidden([ply(F3)], keys(F3)), false);
});

test("pathCrossesHidden: no hidden key on the path is false", () => {
  assert.equal(pathCrossesHidden([ply(F2), ply(F3), ply(F4)], keys(F1)), false);
  assert.equal(pathCrossesHidden([ply(F2), ply(F3)], new Set()), false);
});

test("pathCrossesHidden: empty path, junk and missing keys are false and never throw", () => {
  assert.equal(pathCrossesHidden([], keys(F1)), false);
  assert.equal(pathCrossesHidden(undefined, keys(F1)), false);
  assert.equal(pathCrossesHidden("junk", keys(F1)), false);
  assert.equal(pathCrossesHidden([null, {}, { fen: 5 }, ply(F2)], keys(F1)), false);
  assert.equal(pathCrossesHidden([ply(F2), ply(F3)], undefined), false);
});

test("pathCrossesHidden: the same position with different move counters matches", () => {
  const moved = F3.replace(" 0 3", " 23 51");
  assert.equal(pathCrossesHidden([ply(moved), ply(F4)], keys(F3)), true);
});

test("shouldExitExplore: the existing rule, a hidden selected move, still exits", () => {
  assert.equal(shouldExitExplore({ exploring: true, path: [ply(F2)], hiddenKeys: new Set(), hiddenSelected: true }), true);
});

test("shouldExitExplore: not exploring never exits", () => {
  assert.equal(shouldExitExplore({ exploring: false, path: [ply(F2), ply(F3), ply(F4)], hiddenKeys: keys(F3), hiddenSelected: true }), false);
});

test("shouldExitExplore: a begun path exits once me changes and the hidden set grows past it", () => {
  const path = [ply(F2), ply(F3), ply(F4)];
  // before: me unset, nothing hidden, the full line was begun at the move before the key moment
  const before = hiddenPositionKeys([{ fen_before: F3 }], () => false);
  assert.equal(shouldExitExplore({ exploring: true, path, hiddenKeys: before, hiddenSelected: false }), false);
  // after the user chooses themselves, F3 (their key position) is hidden and the path crosses it
  const after = hiddenPositionKeys([{ fen_before: F3 }], () => true);
  assert.equal(shouldExitExplore({ exploring: true, path, hiddenKeys: after, hiddenSelected: false }), true);
});

test("shouldExitExplore: a path that only ends at the hidden position stays", () => {
  assert.equal(shouldExitExplore({ exploring: true, path: [ply(F2), ply(F3)], hiddenKeys: keys(F3), hiddenSelected: false }), false);
});

test("focusTarget: the toggle when the tabs are hidden, else Analysis, else Coach", () => {
  assert.equal(focusTarget({ tabsHidden: true, analysisDisabled: false }), "toggle");
  assert.equal(focusTarget({ tabsHidden: true, analysisDisabled: true }), "toggle");
  assert.equal(focusTarget({ tabsHidden: false, analysisDisabled: false }), "analysis");
  assert.equal(focusTarget({ tabsHidden: false, analysisDisabled: true }), "coach");
  assert.equal(focusTarget(), "analysis");
});

test("linePlyCounts: a junk line (no moves, null, non-array moves) counts as 0 plies and never throws", () => {
  const lines = [{ moves: [ply(F2), ply(F3)] }, {}, null, { moves: "x" }, { moves: [] }];
  assert.deepEqual(linePlyCounts(lines), [2, 0, 0, 0, 0]);
  assert.deepEqual(linePlyCounts(undefined), []);
});

// The page's decision: the selected move's own start position counts as hidden too (an exact repetition of a key position).
const decide = ({ mv, hidden, hiddenKeys, path }) =>
  shouldExitExplore({ exploring: true, path, hiddenKeys, hiddenSelected: isHiddenTarget({ hidden, mv, hiddenKeys }) });

test("explore start that repeats a hidden key position exits though the move itself is not hidden", () => {
  const path = [ply(F2), ply(F3)];  // does not cross: only the start is hidden
  const mvRepeat = { fen_before: F1.replace(" 0 2", " 9 30") };
  assert.equal(shouldExitExplore({ exploring: true, path, hiddenKeys: keys(F1), hiddenSelected: false }), false);  // the old wiring
  assert.equal(decide({ mv: mvRepeat, hidden: false, hiddenKeys: keys(F1), path }), true);
});

test("explore start that is not a hidden key position does not exit", () => {
  assert.equal(decide({ mv: { fen_before: F4 }, hidden: false, hiddenKeys: keys(F1), path: [ply(F2), ply(F3)] }), false);
});
