// Pure helpers for the analysis bar and engine lines. No window/document at import time.
// Scores are { cp, mate } in White's perspective (cp in centipawns, mate in full moves).
const MATE_CAP = 9000;
const FILL_MIN = 0.02;
const FILL_MAX = 0.98;

/** Convert a stored cp_best (mover's perspective) to White's perspective. */
export function scoreFromStored(cpBest, color) {
  if (typeof cpBest !== "number" || !Number.isFinite(cpBest)) return { cp: 0, mate: null, capped: false };
  const cp = color === "black" ? -cpBest : cpBest;
  return { cp: cp === 0 ? 0 : cp, mate: null, capped: Math.abs(cpBest) >= MATE_CAP };
}

/** One guard for every helper: junk or missing input reads as level (cp 0), never NaN. */
function norm(score) {
  const s = score && typeof score === "object" ? score : {};
  const cp = typeof s.cp === "number" && Number.isFinite(s.cp) ? s.cp : 0;
  const mate = typeof s.mate === "number" && Number.isFinite(s.mate) ? Math.trunc(s.mate) : null;
  return { cp, mate, capped: s.capped === true };
}

/** +1 White is mating/winning, -1 Black, 0 unknown (only for a mate with no distance and cp 0). */
function mateSign(s) {
  if (s.mate !== 0) return s.mate > 0 ? 1 : -1;
  return Math.sign(s.cp);
}

export function formatScore(score, decimals = 2) {
  const s = norm(score);
  if (s.mate === 0) return "Mate";
  if (s.mate !== null) return s.mate < 0 ? `-M${-s.mate}` : `M${s.mate}`;
  if (s.capped) return "Mate";
  const scale = 10 ** decimals;
  const n = Math.round((Math.abs(s.cp) * scale) / 100);
  const text = (n / scale).toFixed(decimals);
  if (n === 0) return text;
  return (s.cp < 0 ? "-" : "+") + text;
}

/** White's share of the bar in [0.02, 0.98]; always finite. */
export function barFill(score) {
  const s = norm(score);
  if (s.mate !== null || s.capped) {
    const sign = s.mate !== null ? mateSign(s) : Math.sign(s.cp);
    return sign < 0 ? FILL_MIN : sign > 0 ? FILL_MAX : 0.5;
  }
  // tanh is smooth and odd, so fill(+x) + fill(-x) = 1. 0.48 keeps the curve inside the
  // [0.02, 0.98] clamp with a margin; the 800 cp scale makes one pawn (100 cp) move the bar
  // about 6 points while leads beyond roughly 3 pawns flatten out towards the clamp.
  const a = 0.48 * Math.tanh(Math.abs(s.cp) / 800);
  const f = s.cp < 0 ? 0.5 - a : 0.5 + a;
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
  const sc = norm(score);
  let s;
  if (sc.mate !== null && sc.mate !== 0) {
    s = `mate in ${Math.abs(sc.mate)} for ${sc.mate > 0 ? "White" : "Black"}`;
  } else if (sc.mate === 0 || sc.capped) {
    const sign = Math.sign(sc.cp);
    s = sign === 0 ? "mate" : `mate for ${sign > 0 ? "White" : "Black"}`;
  } else {
    const f = formatScore(sc);
    s = f.startsWith("+") ? `plus ${f.slice(1)}` : f.startsWith("-") ? `minus ${f.slice(1)}` : f;
  }
  return `Line ${index}, ${s}, ${text}`;
}

/**
 * Debounced, cached, token-guarded live analysis. `api.analysePosition(fen)` does the request; `ui` gets
 * thinking(fen) / loaded(fen, response) / gameOver(fen, result) / error(fen, message) / busyDim().
 * request() is called on every render, so asking again for the FEN already pending, in flight, loaded or
 * failed is a no-op (retry() is the explicit way out of an error).
 */
export function createAnalysis({ api, ui, delay = 250, retries = 2, retryDelay = 600, timer } = {}) {
  const clock = timer || { set: (fn, ms) => setTimeout(fn, ms), clear: (h) => clearTimeout(h) };
  const cache = new Map();   // fen -> successful response (including game over)
  let token = 0, handle = null, current = null, status = "idle";

  const cancel = () => { token += 1; if (handle !== null) { clock.clear(handle); handle = null; } current = null; status = "idle"; };
  const deliver = (fen, resp) => {
    status = "loaded";
    if (resp.game_over) ui.gameOver(fen, resp.result); else ui.loaded(fen, resp);
  };

  async function run(fen, my, attempt) {
    handle = null;
    let resp;
    try { resp = await api.analysePosition(fen); }
    catch (e) {
      if (my !== token) return;
      if (e && e.busy && attempt < retries) {
        ui.busyDim();
        handle = clock.set(() => run(fen, my, attempt + 1), retryDelay);
        return;
      }
      status = "error";
      ui.error(fen, (e && e.message) || "Analysis failed");
      return;
    }
    if (my !== token) return;
    cache.set(fen, resp);
    deliver(fen, resp);
  }

  return {
    request(fen, { enabled } = {}) {
      if (!enabled || !fen) { if (status !== "idle" || handle !== null) cancel(); return; }
      if (fen === current && status !== "idle") return;
      cancel();
      current = fen;
      const hit = cache.get(fen);
      if (hit) { deliver(fen, hit); return; }
      status = "thinking";
      ui.thinking(fen);
      const my = token;
      handle = clock.set(() => run(fen, my, 0), delay);
    },
    retry() {
      if (status !== "error" || current === null) return;
      const fen = current;
      token += 1; status = "thinking";
      ui.thinking(fen);
      run(fen, token, 0);
    },
    invalidate() { cancel(); },
    peek(fen) { return cache.get(fen) || null; },
  };
}
