import { test } from "node:test";
import assert from "node:assert/strict";
import {
  plural, pct, lossText, recordText, levelOf, barPercent, resultShares, rollingMean, trendGeometry,
  pickPlayer, storedMe,
} from "../../src/chess_coach/web/js/stats-view.js";

test("plural and the record read naturally", () => {
  assert.equal(plural(1, "game"), "1 game");
  assert.equal(plural(2, "loss", "losses"), "2 losses");
  assert.equal(recordText({ wins: 29, draws: 1, losses: 19 }), "29 wins · 1 draw · 19 losses");
});

test("percentages and loss text handle empty values", () => {
  assert.equal(pct(5, 20), "25.0%");
  assert.equal(pct(0, 0), "–");
  assert.equal(lossText(0.0345), "3.5%");
  assert.equal(lossText(null), "–");
});

test("a group is compared with the player's own average, and small groups are not judged", () => {
  assert.equal(levelOf(0.6, false), "good");
  assert.equal(levelOf(1.0, false), "even");
  assert.equal(levelOf(1.4, false), "poor");
  assert.equal(levelOf(0.8, false), "good");
  assert.equal(levelOf(1.25, false), "poor");
  assert.equal(levelOf(0.5, true), "few");
  assert.equal(levelOf(null, false), "none");
  assert.equal(levelOf(NaN, false), "none");
});

test("bar length is relative to the longest, with a visible sliver for small non-zero values", () => {
  assert.equal(barPercent(50, 100), 50);
  assert.equal(barPercent(100, 100), 100);
  assert.equal(barPercent(0.1, 100), 3);
  assert.equal(barPercent(0, 100), 0);
  assert.equal(barPercent(5, 0), 0);
});

test("result shares are whole percents that always add to 100", () => {
  for (const r of [{ wins: 1, draws: 1, losses: 1 }, { wins: 8, draws: 0, losses: 3 }, { wins: 5, draws: 0, losses: 6 }]) {
    const s = resultShares(r);
    assert.equal(s.win + s.draw + s.loss, 100);
  }
  assert.deepEqual(resultShares({ wins: 0, draws: 0, losses: 0 }), { win: 0, draw: 0, loss: 0 });
});

test("the rolling mean looks back over the window and skips missing values", () => {
  assert.deepEqual(rollingMean([10, 20, 30], 2), [10, 15, 25]);
  assert.deepEqual(rollingMean([10, null, 30], 5), [10, 10, 20]);
  assert.deepEqual(rollingMean([null, null], 3), [null, null]);
});

test("the trend chart needs two games and keeps every dot inside the drawing", () => {
  assert.equal(trendGeometry([{ accuracy: 90, result: "win", game_id: 1 }]), null);
  const t = [80, 92, 85, 97].map((accuracy, i) => ({ accuracy, result: "win", game_id: i }));
  const g = trendGeometry(t, { width: 400, height: 100, pad: 10 });
  assert.equal(g.dots.length, 4);
  for (const d of g.dots) {
    assert.ok(d.x >= 10 && d.x <= 390, `x ${d.x}`);
    assert.ok(d.y >= 10 && d.y <= 90, `y ${d.y}`);
  }
  assert.ok(g.dots[3].y < g.dots[0].y, "a higher accuracy is drawn higher up");
  assert.equal(g.line.split(" ").length, 4);
});

test("the player shown is the query, else what the board page remembered, else the suggestion, else the first", () => {
  const players = [{ name: "Ann" }, { name: "Bo" }];
  assert.equal(pickPlayer({ query: "bo", stored: "Ann", players }), "Bo");
  assert.equal(pickPlayer({ query: "zzz", stored: "ann", players }), "Ann");
  assert.equal(pickPlayer({ stored: "nope", suggested: "Bo", players }), "Bo");
  assert.equal(pickPlayer({ players }), "Ann");
  assert.equal(pickPlayer({ players: [] }), null);
});

test("the remembered name is read safely", () => {
  assert.equal(storedMe('"Logic911e"'), "Logic911e");
  assert.equal(storedMe("null"), null);
  assert.equal(storedMe("not json"), null);
  assert.equal(storedMe(null), null);
});
