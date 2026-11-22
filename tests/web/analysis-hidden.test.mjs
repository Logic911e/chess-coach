import { test } from "node:test";
import assert from "node:assert/strict";
import {
  positionKey, hiddenPositionKeys, truncateLines, isHiddenTarget, selectableLine,
  shouldRequest, linesState, linesView, barView,
} from "../../src/chess_coach/web/js/analysis-ui.js";
import { createExplore } from "../../src/chess_coach/web/js/explore.js";
import { settleWithin } from "../../src/chess_coach/web/js/me.js";

const F0 = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2";  // before the opponent's move (idx-1)
const F1 = "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 2";  // the key position (idx)
const F2 = "r1bqkbnr/pppp1ppp/2n5/8/3pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 3";
const F3 = "r1bqkbnr/pppp1ppp/2n5/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 3";
const mv = (fen_before, extra = {}) => ({ fen_before, ...extra });
const ply = (san, fen) => ({ san, uci: "a1a2", fen, capture: false, check: false });
const deepFreeze = (o) => { Object.values(o).forEach((v) => v && typeof v === "object" && deepFreeze(v)); return Object.freeze(o); };

test("positionKey keeps the first four FEN fields, so move counters never matter", () => {
  assert.equal(positionKey(F1), "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3");
  assert.equal(positionKey(F1), positionKey(F1.replace(" 0 2", " 17 40")));
  assert.notEqual(positionKey(F1), positionKey(F1.replace(" b ", " w ")));
});

test("hiddenPositionKeys: empty when nothing is hidden", () => {
  const moves = [mv(F0), mv(F1), mv(F2)];
  assert.equal(hiddenPositionKeys(moves, () => false).size, 0);
  assert.equal(hiddenPositionKeys([], () => true).size, 0);
});

test("hiddenPositionKeys: the fen_before of every hidden move, counters ignored", () => {
  const moves = [mv(F0, { id: 1 }), mv(F1, { id: 2 }), mv(F2, { id: 3 })];
  const keys = hiddenPositionKeys(moves, (m) => m.id === 2);
  assert.deepEqual([...keys], [positionKey(F1)]);
  assert.ok(keys.has(positionKey(F1.replace(" 0 2", " 9 9"))));
});

test("truncateLines: a line stops at the ply that reaches a hidden position (second ply gone)", () => {
  const keys = new Set([positionKey(F1)]);
  const lines = [{ score: { cp: 30 }, moves: [ply("d4", F1), ply("exd4", F2), ply("Nxd4", F3)] }];
  const out = truncateLines(lines, keys);
  assert.deepEqual(out[0].moves.map((m) => m.san), ["d4"]);
  assert.equal(out[0].score, lines[0].score);
});

test("truncateLines: a line reaching the position at ply 3 keeps 3 plies", () => {
  const keys = new Set([positionKey(F3)]);
  const lines = [{ moves: [ply("d4", F1), ply("exd4", F2), ply("Nxd4", F3), ply("Nf6", F0)] }];
  assert.deepEqual(truncateLines(lines, keys)[0].moves.map((m) => m.san), ["d4", "exd4", "Nxd4"]);
});

test("truncateLines: lines that never reach a hidden position are unchanged; empty keys change nothing", () => {
  const lines = [{ moves: [ply("d4", F1), ply("exd4", F2)] }];
  assert.deepEqual(truncateLines(lines, new Set([positionKey(F3)])), lines);
  assert.deepEqual(truncateLines(lines, new Set()), lines);
});

test("truncateLines: never mutates its input and returns new arrays", () => {
  const lines = deepFreeze([{ moves: [ply("d4", F1), ply("exd4", F2)] }, { moves: [ply("Nc3", F0)] }]);
  const out = truncateLines(lines, new Set([positionKey(F1)]));
  assert.notEqual(out, lines);
  assert.notEqual(out[0].moves, lines[0].moves);
  assert.equal(lines[0].moves.length, 2);
  assert.equal(out[0].moves.length, 1);
  assert.deepEqual(truncateLines(undefined, new Set()), []);
});

test("transposition: a different move whose position equals a hidden one is hidden", () => {
  const moves = [mv(F1, { id: 1 }), mv(F1.replace(" 0 2", " 5 7"), { id: 2 })];
  const keys = hiddenPositionKeys(moves, (m) => m.id === 1);
  assert.equal(isHiddenTarget({ hidden: false, mv: moves[1], hiddenKeys: keys }), true);
  assert.equal(isHiddenTarget({ hidden: false, mv: mv(F0), hiddenKeys: keys }), false);
  assert.equal(isHiddenTarget({ hidden: true, mv: mv(F0), hiddenKeys: new Set() }), true);
});

test("selectableLine: refuses a hidden target and truncates what explore.begin receives", () => {
  const keys = new Set([positionKey(F1)]);
  const resp = { lines: [{ moves: [ply("d4", F1), ply("exd4", F2), ply("Nxd4", F3)] }] };
  const moves = selectableLine({ resp, i: 0, target: mv(F0), hidden: false, hiddenKeys: keys });
  assert.deepEqual(moves.map((m) => m.san), ["d4"]);
  const ex = createExplore();
  ex.begin(moves);
  assert.equal(ex.path().length, 1);
  assert.equal(ex.position().fen, F1);
  // the explored position is itself hidden: nothing may continue from it
  assert.equal(selectableLine({ resp, i: 0, target: mv(F1), hidden: false, hiddenKeys: keys }), null);
  assert.equal(selectableLine({ resp, i: 0, target: mv(F0), hidden: true, hiddenKeys: keys }), null);
  assert.equal(selectableLine({ resp, i: 5, target: mv(F0), hidden: false, hiddenKeys: keys }), null);
  assert.equal(selectableLine({ resp: null, i: 0, target: mv(F0), hidden: false, hiddenKeys: keys }), null);
});

test("an explored position in hiddenKeys: no request, neutral bar, hidden lines, nothing clickable", () => {
  const keys = new Set([positionKey(F1)]);
  const explored = mv(F1);
  assert.equal(shouldRequest({ mv: explored, hidden: false, analysisOn: true, hiddenKeys: keys }), false);
  assert.equal(shouldRequest({ mv: explored, hidden: false, analysisOn: true, hiddenKeys: new Set() }), true);
  const peek = () => ({ lines: [{ score: { cp: 50 }, moves: [ply("d4", F1)] }] });
  const ls = linesState({ mv: explored, hidden: false, analysisOn: true, peek, status: null, hiddenKeys: keys });
  assert.equal(ls.kind, "hidden");
  const v = linesView(ls);
  assert.equal(v.rows.length, 0);
  assert.equal(v.note, "Hidden until you guess");
  const hidden = isHiddenTarget({ hidden: false, mv: explored, hiddenKeys: keys });
  const bar = barView({ score: { cp: 900 }, hidden });
  assert.equal(bar.hidden, true);
  assert.equal(bar.label, "");
  assert.equal(bar.fill, 0.5);
  assert.equal(bar.aria, "Evaluation hidden until you guess");
});

test("linesState loaded: the lines panel shows truncated lines, the cached response is untouched", () => {
  const keys = new Set([positionKey(F1)]);
  const resp = deepFreeze({ version: "Stockfish 17", depth: 16,
    lines: [{ score: { cp: 30 }, moves: [ply("d4", F1), ply("exd4", F2)] }] });
  const ls = linesState({ mv: mv(F0), hidden: false, analysisOn: true, peek: () => resp, hiddenKeys: keys });
  assert.equal(ls.kind, "loaded");
  assert.equal(ls.response, resp);
  const v = linesView(ls);
  assert.equal(v.rows.length, 1);
  assert.ok(!/dxe|exd4/.test(v.rows[0].text), v.rows[0].text);
  assert.equal(resp.lines[0].moves.length, 2);
});

test("settleWithin resolves on settle (even a rejection) or after the time limit", async () => {
  await settleWithin(Promise.reject(new Error("x")), 1000);
  const t0 = Date.now();
  await settleWithin(new Promise(() => {}), 30);
  assert.ok(Date.now() - t0 >= 25);
  assert.equal(await settleWithin(Promise.resolve(5), 1000), 5);
});
