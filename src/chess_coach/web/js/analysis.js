// Pure helpers for the analysis bar and engine lines. No window/document at import time.
// Scores are { cp, mate } in White's perspective (cp in centipawns, mate in full moves).
const MATE_CAP = 9000;
const FILL_MIN = 0.02;
const FILL_MAX = 0.98;

/** Convert a stored cp_best (mover's perspective) to White's perspective. */
export function scoreFromStored(cpBest, color) {
  const cp = color === "black" ? -cpBest : cpBest;
  return { cp: cp === 0 ? 0 : cp, mate: null, capped: Math.abs(cpBest) >= MATE_CAP };
}

function isMate(score) { return score.mate !== null && score.mate !== undefined; }

function whiteSign(score) {
  if (isMate(score)) return score.mate > 0 ? 1 : -1;
  return score.cp > 0 ? 1 : score.cp < 0 ? -1 : 0;
}

export function formatScore(score, decimals = 2) {
  if (isMate(score)) return score.mate < 0 ? `-M${-score.mate}` : `M${score.mate}`;
  if (score.capped) return "Mate";
  const scale = 10 ** decimals;
  const n = Math.round((Math.abs(score.cp) * scale) / 100);
  const text = (n / scale).toFixed(decimals);
  if (n === 0) return text;
  return (score.cp < 0 ? "-" : "+") + text;
}

/** White's share of the bar in [0.02, 0.98]. */
export function barFill(score) {
  if (isMate(score) || score.capped) return whiteSign(score) < 0 ? FILL_MIN : FILL_MAX;
  const a = 0.48 * Math.tanh(Math.abs(score.cp) / 800);
  const f = score.cp < 0 ? 0.5 - a : 0.5 + a;
  return Math.min(FILL_MAX, Math.max(FILL_MIN, f));
}

export function barLabel(score) { return formatScore(score, 1); }

/** SAN moves numbered from the FEN's move number and side to move (labelling only). */
export function lineText(fen, moves, maxPlies = 8) {
  const parts = String(fen || "").split(" ");
  let black = parts[1] === "b";
  let num = parseInt(parts[5], 10);
  if (!Number.isFinite(num) || num < 1) num = 1;
  const shown = (moves || []).slice(0, maxPlies);
  const out = [];
  shown.forEach((m, i) => {
    if (!black) out.push(`${num}.`);
    else if (i === 0) out.push(`${num}...`);
    out.push(m.san);
    if (black) num += 1;
    black = !black;
  });
  let text = out.join(" ");
  if ((moves || []).length > maxPlies) text += " ...";
  return text;
}

export function lineA11yName(index, score, text) {
  let s;
  if (isMate(score)) s = `mate in ${Math.abs(score.mate)} for ${score.mate > 0 ? "White" : "Black"}`;
  else if (score.capped) s = `mate for ${score.cp > 0 ? "White" : "Black"}`;
  else {
    const f = formatScore(score);
    s = f.startsWith("+") ? `plus ${f.slice(1)}` : f.startsWith("-") ? `minus ${f.slice(1)}` : f;
  }
  return `Line ${index}, ${s}, ${text}`;
}
