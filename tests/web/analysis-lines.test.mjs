import { test } from "node:test";
import assert from "node:assert/strict";
import { linesView, renderLines } from "../../src/chess_coach/web/js/analysis-ui.js";

const FEN = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 11";
const mv = (...s) => s.map((san) => ({ san }));
const RESP = {
  game_over: false, version: "17", depth: 18,
  lines: [
    { score: { cp: 35, mate: null }, moves: mv("Qe2", "Re8", "Rfe1") },
    { score: { cp: -120, mate: null }, moves: mv("h3") },
    { score: { cp: null, mate: -3 }, moves: mv("a3") },
  ],
};

test("loaded: header, one row per line, badge side, text and accessible name", () => {
  const v = linesView({ kind: "loaded", fen: FEN, response: RESP });
  assert.equal(v.header, "Stockfish 17 · depth 18");
  assert.equal(v.rows.length, 3);
  assert.deepEqual(v.rows.map((r) => r.badge), ["white", "black", "black"]);
  assert.deepEqual(v.rows.map((r) => r.scoreText), ["+0.35", "-1.20", "-M3"]);
  assert.equal(v.rows[0].text, "11. Qe2 Re8 12. Rfe1");
  assert.equal(v.rows[0].name, "Line 1, plus 0.35, 11. Qe2 Re8 12. Rfe1");
  assert.equal(v.note, "");
});

test("a version that already names the engine is not prefixed twice", () => {
  assert.equal(linesView({ kind: "loaded", fen: FEN, response: { ...RESP, version: "Stockfish 19" } }).header, "Stockfish 19 · depth 18");
});

test("loaded with a null version reads just Stockfish; missing depth is left out", () => {
  assert.equal(linesView({ kind: "loaded", fen: FEN, response: { ...RESP, version: null } }).header, "Stockfish · depth 18");
  assert.equal(linesView({ kind: "loaded", fen: FEN, response: { ...RESP, version: null, depth: undefined } }).header, "Stockfish");
});

test("loaded with no or junk lines shows a note, no rows", () => {
  const v = linesView({ kind: "loaded", fen: FEN, response: { lines: [] } });
  assert.equal(v.rows.length, 0);
  assert.ok(v.note);
  assert.doesNotThrow(() => linesView({ kind: "loaded", fen: FEN, response: null }));
});

test("thinking: three skeleton rows, no real rows", () => {
  const v = linesView({ kind: "thinking", fen: FEN });
  assert.equal(v.skeleton, 3);
  assert.equal(v.rows.length, 0);
  assert.match(v.note, /thinking/i);
});

test("error: message and a retry button", () => {
  const v = linesView({ kind: "error", fen: FEN, message: "Stockfish crashed" });
  assert.equal(v.note, "Stockfish crashed");
  assert.equal(v.retry, true);
  assert.match(linesView({ kind: "error" }).note, /./);
});

test("game over: a clear note per result", () => {
  assert.equal(linesView({ kind: "gameOver", result: "checkmate" }).note, "Checkmate");
  assert.equal(linesView({ kind: "gameOver", result: "stalemate" }).note, "Stalemate");
  assert.equal(linesView({ kind: "gameOver", result: "draw" }).note, "Draw");
  assert.equal(linesView({ kind: "gameOver", result: "???" }).note, "Game over");
  assert.equal(linesView({ kind: "gameOver", result: "draw" }).rows.length, 0);
});

test("hidden and no-game reuse analysisNote and carry nothing else", () => {
  for (const [state, note] of [[{ kind: "hidden" }, "Hidden until you guess"], [{ kind: "noGame" }, "No game loaded"]]) {
    const v = linesView(state);
    assert.equal(v.note, note);
    assert.equal(v.header, "");
    assert.equal(v.rows.length, 0);
    assert.equal(v.skeleton, 0);
  }
});

// ---- tiny fake DOM ----
function fakeDoc() {
  const mk = (tag) => {
    const e = { tag, children: [], attrs: {}, dataset: {}, style: {}, className: "", textContent: "", listeners: {} };
    e.append = (...k) => { e.children.push(...k); };
    e.replaceChildren = (...k) => { e.children = [...k]; };
    e.setAttribute = (n, v) => { e.attrs[n] = String(v); };
    e.addEventListener = (n, f) => { e.listeners[n] = f; };
    return e;
  };
  const doc = { createElement: mk };
  const panel = mk("div"); panel.ownerDocument = doc;
  return panel;
}
const walk = (e, out = []) => { out.push(e); e.children.forEach((c) => walk(c, out)); return out; };

test("renderLines: each line is a focusable button with the accessible name, score badge and text", () => {
  const panel = fakeDoc();
  const picked = [];
  renderLines(panel, { kind: "loaded", fen: FEN, response: RESP }, { onSelect: (i) => picked.push(i) });
  const btns = walk(panel).filter((e) => e.tag === "button");
  assert.equal(btns.length, 3);
  assert.equal(btns[0].type, "button");
  assert.equal(btns[0].attrs["aria-label"], "Line 1, plus 0.35, 11. Qe2 Re8 12. Rfe1");
  const badge = walk(btns[1]).find((e) => /badge/.test(e.className));
  assert.equal(badge.textContent, "-1.20");
  assert.match(badge.className, /black/);
  assert.match(walk(btns[0]).find((e) => /badge/.test(e.className)).className, /white/);
  btns[2].listeners.click();
  assert.deepEqual(picked, [2]);
});

test("renderLines: error state renders a Retry button that calls onRetry; rebuilds on each call", () => {
  const panel = fakeDoc();
  let n = 0;
  renderLines(panel, { kind: "error", fen: FEN, message: "boom" }, { onRetry: () => { n += 1; } });
  const retry = walk(panel).find((e) => e.tag === "button");
  assert.equal(retry.textContent, "Retry");
  retry.listeners.click();
  assert.equal(n, 1);
  assert.ok(walk(panel).some((e) => e.textContent === "boom"));
  renderLines(panel, { kind: "gameOver", result: "draw" });
  assert.ok(!walk(panel).some((e) => e.tag === "button"));
  assert.ok(walk(panel).some((e) => e.textContent === "Draw"));
});

test("renderLines: thinking draws skeleton rows (no buttons)", () => {
  const panel = fakeDoc();
  renderLines(panel, { kind: "thinking", fen: FEN });
  assert.equal(walk(panel).filter((e) => /skeleton/.test(e.className)).length, 3);
  assert.ok(!walk(panel).some((e) => e.tag === "button"));
});
