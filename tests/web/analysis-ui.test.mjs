import { test } from "node:test";
import assert from "node:assert/strict";
import { barView, analysisNote, barText, effectiveTab } from "../../src/chess_coach/web/js/analysis-ui.js";

const W = (cp) => ({ cp, mate: null, capped: false });

test("barView: a stored value shows the fill, the label and the aria text", () => {
  const v = barView({ score: W(40), hidden: false, off: false, flipped: false, live: false });
  assert.equal(v.hidden, false);
  assert.equal(v.off, false);
  assert.ok(v.fill > 0.5 && v.fill < 0.6);
  assert.equal(v.label, "+0.4");
  assert.equal(v.aria, "Evaluation: White is ahead by 0.4 pawns");
  assert.equal(v.whiteOnTop, false);
  assert.equal(v.labelOnTop, false);  // White leads, White is at the bottom
  assert.equal(v.dim, false);
});

test("barView: Black ahead puts the label at Black's end", () => {
  const v = barView({ score: W(-120), hidden: false, off: false, flipped: false, live: false });
  assert.ok(v.fill < 0.5);
  assert.equal(v.label, "-1.2");
  assert.equal(v.aria, "Evaluation: Black is ahead by 1.2 pawns");
  assert.equal(v.labelOnTop, true);
});

test("barView: flipped moves White's end to the top and the label with it", () => {
  const a = barView({ score: W(40), hidden: false, off: false, flipped: true, live: false });
  assert.equal(a.whiteOnTop, true);
  assert.equal(a.labelOnTop, true);
  assert.equal(a.fill, barView({ score: W(40), flipped: false }).fill);  // the share does not change
  const b = barView({ score: W(-40), hidden: false, off: false, flipped: true, live: false });
  assert.equal(b.labelOnTop, false);
});

test("barView: hidden is neutral with no label and a neutral aria text", () => {
  const v = barView({ score: W(900), hidden: true, off: false, flipped: false, live: false });
  assert.equal(v.hidden, true);
  assert.equal(v.fill, 0.5);
  assert.equal(v.label, "");
  assert.equal(v.aria, "Evaluation hidden until you guess");
});

test("barView: off is reported and shows nothing", () => {
  const v = barView({ score: W(300), hidden: false, off: true, flipped: false, live: false });
  assert.equal(v.off, true);
  assert.equal(v.label, "");
});

test("barView: level, missing and junk scores read as level", () => {
  for (const s of [W(0), undefined, null, { cp: NaN }, "x", {}]) {
    const v = barView({ score: s, hidden: false, off: false, flipped: false, live: false });
    assert.equal(v.fill, 0.5);
    assert.equal(v.aria, "Evaluation: level");
    assert.equal(v.label, "0.0");
    assert.equal(v.labelOnTop, false);
  }
});

test("barView: mate scores", () => {
  const w = barView({ score: { cp: 0, mate: 3, capped: false }, hidden: false, off: false, flipped: false, live: true });
  assert.equal(w.label, "M3");
  assert.equal(w.aria, "Evaluation: mate for White");
  const capped = barView({ score: { cp: -9000, mate: null, capped: true }, flipped: false });
  assert.equal(capped.label, "M");
  assert.equal(capped.aria, "Evaluation: mate for Black");
});

test("barView: dim only when asked and never when hidden", () => {
  assert.equal(barView({ score: W(10), live: true, dim: true }).dim, true);
  assert.equal(barView({ score: W(10), hidden: true, dim: true }).dim, false);
});

test("analysisNote: neutral text while hidden", () => {
  assert.equal(analysisNote({ hidden: true }), "Hidden until you guess");
  assert.notEqual(analysisNote({ hidden: false }), "Hidden until you guess");
});

test("barView: labelOn follows the leader and the label sits at that colour's end, flipped or not", () => {
  const cases = [
    // [cp, flipped, labelOn, labelOnTop]
    [40, false, "white", false], [-40, false, "black", true],
    [40, true, "white", true], [-40, true, "black", false],
    [0, false, "white", false], [0, true, "white", true],
  ];
  for (const [cp, flipped, on, top] of cases) {
    const v = barView({ score: W(cp), flipped });
    assert.equal(v.labelOn, on, `cp ${cp} flipped ${flipped}`);
    assert.equal(v.labelOnTop, top, `cp ${cp} flipped ${flipped}`);
  }
  assert.equal(barView({ score: { cp: 0, mate: -2 }, flipped: true }).labelOn, "black");
});

test("barText: short bar-only forms", () => {
  assert.equal(barText(W(40)), "+0.4");
  assert.equal(barText(W(-120)), "-1.2");
  assert.equal(barText(W(1050)), "+11");
  assert.equal(barText(W(-1000)), "-10");
  assert.equal(barText(W(990)), "+9.9");
  assert.equal(barText({ cp: 0, mate: 12 }), "M12");
  assert.equal(barText({ cp: 0, mate: -12 }), "-M12");
  assert.equal(barText({ cp: 9000, mate: null, capped: true }), "M");
  assert.equal(barText(undefined), "0.0");
});

test("no game: neutral level bar that says so, never the guess message", () => {
  const v = barView({ score: undefined, noGame: true });
  assert.equal(v.aria, "No game loaded");
  assert.equal(v.fill, 0.5);
  assert.equal(v.label, "");
  assert.equal(analysisNote({ noGame: true }), "No game loaded");
  assert.equal(analysisNote({ noGame: true, hidden: true }), "No game loaded");
  assert.ok(!/guess/i.test(v.aria));
});

test("effectiveTab: Coach while hidden or off, otherwise the saved tab", () => {
  assert.equal(effectiveTab({ saved: "analysis", hidden: true, on: true }), "coach");
  assert.equal(effectiveTab({ saved: "analysis", hidden: false, on: true }), "analysis");
  assert.equal(effectiveTab({ saved: "analysis", hidden: false, on: false }), "coach");
  assert.equal(effectiveTab({ saved: "coach", hidden: false, on: true }), "coach");
  assert.equal(effectiveTab({ saved: "junk", hidden: false, on: true }), "coach");
});
