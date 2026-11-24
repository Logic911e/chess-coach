// Pure helpers for the stats page (no DOM, no window): they import cleanly in node and are tested there.

export const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

/** "82.7%" for n of d, or an en dash when there is nothing to divide. */
export const pct = (n, d) => (d ? `${(100 * n / d).toFixed(1)}%` : "–");

/** Win-chance lost per move, as the page says it: 0.0345 -> "3.5%". */
export const lossText = (loss) => (loss == null ? "–" : `${(100 * loss).toFixed(1)}%`);

export const recordText = (o) =>
  `${plural(o.wins, "win")} · ${plural(o.draws, "draw")} · ${plural(o.losses, "loss", "losses")}`;

/**
 * How a group compares with the player's OWN average: ratio = its loss / their overall loss.
 * "few" when there are too few moves or games to read anything from it.
 */
export function levelOf(ratio, small) {
  if (small) return "few";
  if (ratio == null || !Number.isFinite(ratio)) return "none";
  if (ratio <= 0.8) return "good";
  if (ratio >= 1.25) return "poor";
  return "even";
}

export const LEVEL_TEXT = {
  good: "better than your average", even: "about your average", poor: "worse than your average",
  few: "too few to judge", none: "",
};

/** Bar length as a percentage of the longest bar, never below a visible sliver for a non-zero value. */
export function barPercent(value, max) {
  if (!(value > 0) || !(max > 0)) return 0;
  return Math.min(100, Math.max(3, (100 * value) / max));
}

/** Win, draw and loss shares of an opening's games as whole percents that add to 100. */
export function resultShares({ wins, draws, losses }) {
  const total = wins + draws + losses;
  if (!total) return { win: 0, draw: 0, loss: 0 };
  const win = Math.round((100 * wins) / total), draw = Math.round((100 * draws) / total);
  return { win, draw, loss: 100 - win - draw };
}

/** Mean of each value and the (up to) window-1 before it; nulls are skipped, a run of nulls gives null. */
export function rollingMean(values, window = 5) {
  return values.map((_, i) => {
    const slice = values.slice(Math.max(0, i - window + 1), i + 1).filter((v) => v != null);
    return slice.length ? slice.reduce((a, b) => a + b, 0) / slice.length : null;
  });
}

/** SVG coordinates for the accuracy-per-game chart: the dots, and the rolling average as a line. */
export function trendGeometry(trend, { width = 640, height = 150, pad = 14, window = 5 } = {}) {
  const acc = trend.map((t) => t.accuracy);
  const known = acc.filter((v) => v != null);
  if (known.length < 2) return null;
  // axis ends on multiples of 10, so the middle label is a round number too
  const lo = Math.floor(Math.min(...known) / 10) * 10, hi = Math.min(100, Math.ceil(Math.max(...known) / 10) * 10);
  const top = Math.max(hi, lo + 10);
  const x = (i) => pad + (i * (width - 2 * pad)) / (trend.length - 1);
  const y = (v) => pad + ((top - v) * (height - 2 * pad)) / (top - lo);
  const dots = trend.map((t, i) => (t.accuracy == null ? null : { x: x(i), y: y(t.accuracy), result: t.result, game: t.game_id }))
    .filter(Boolean);
  const avg = rollingMean(acc, window).map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean);
  return { dots, line: avg.join(" "), lo, hi: top, width, height };
}

/** Which player to show: ?player= if known, else the one remembered by the board page, else the suggestion, else the first. */
export function pickPlayer({ query, stored, players, suggested } = {}) {
  const names = (players || []).map((p) => p.name);
  const ci = (n) => names.find((x) => x.toLowerCase() === String(n || "").toLowerCase());
  return ci(query) || ci(stored) || ci(suggested) || names[0] || null;
}

/** What the player stored for "me" on the board page (a JSON string in localStorage), or null. */
export function storedMe(raw) {
  try { const v = JSON.parse(raw); return typeof v === "string" && v ? v : null; } catch (e) { return null; }
}
