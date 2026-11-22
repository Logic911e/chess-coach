// Evaluation bar and tabs. barView is pure; the render adapters touch the DOM only inside their bodies.
import { barFill, formatScore, lineText, lineA11yName, pathWindow } from "./analysis.js";

const NEUTRAL_ARIA = "Evaluation hidden until you guess";

function side(score) {
  const s = score && typeof score === "object" ? score : {};
  const cp = typeof s.cp === "number" && Number.isFinite(s.cp) ? s.cp : 0;
  const mate = typeof s.mate === "number" && Number.isFinite(s.mate) ? Math.trunc(s.mate) : null;
  if (mate !== null && mate !== 0) return mate > 0 ? 1 : -1;
  return Math.sign(cp);
}

function ariaFor(score) {
  const s = score && typeof score === "object" ? score : {};
  const sign = side(score);
  if (sign === 0 && !(s.mate === 0 || s.capped === true)) return "Evaluation: level";
  const who = sign < 0 ? "Black" : "White";
  if ((typeof s.mate === "number" && Number.isFinite(s.mate)) || s.capped === true) return `Evaluation: mate for ${who}`;
  const pawns = formatScore(score, 1).replace(/^[+-]/, "");
  return pawns === "0.0" ? "Evaluation: level" : `Evaluation: ${who} is ahead by ${pawns} pawns`;
}

/** Short text for the narrow bar only: 10+ pawns without decimals, mate as M<n>, a stored mate cap as M. */
export function barText(score) {
  const s = score && typeof score === "object" ? score : {};
  const mate = typeof s.mate === "number" && Number.isFinite(s.mate) ? Math.trunc(s.mate) : null;
  if (mate === 0) return "M";
  if (mate !== null) return mate < 0 ? `-M${-mate}` : `M${mate}`;
  if (s.capped === true) return "M";
  const f = formatScore(score, 1);
  const n = parseFloat(f);
  return Math.abs(n) >= 10 ? (n < 0 ? "-" : "+") + Math.round(Math.abs(n)) : f;
}

// ---- neutrality over the WHOLE game (a line must never reach or pass a position the user has to guess) ----

/** A position without its move counters: placement, side to move, castling, en passant. */
export const positionKey = (fen) => (typeof fen === "string" ? fen.split(" ").slice(0, 4).join(" ") : "");

/** Keys of the position before every move the page must keep neutral (isHiddenFn is the page's hidden predicate). */
export function hiddenPositionKeys(moves, isHiddenFn) {
  const keys = new Set();
  for (const m of Array.isArray(moves) ? moves : []) {
    if (m && typeof m.fen_before === "string" && m.fen_before && isHiddenFn(m)) keys.add(positionKey(m.fen_before));
  }
  return keys;
}

/**
 * Cuts every line after the first ply that reaches a hidden position: a line may arrive there but never go past it.
 * Returns new arrays and objects; the input (the cached server response) is never mutated.
 */
export function truncateLines(lines, hiddenKeys) {
  if (!Array.isArray(lines)) return [];
  return lines.map((l) => {
    if (!l || !Array.isArray(l.moves)) return l;
    const cut = hiddenKeys ? l.moves.findIndex((m) => m && hiddenKeys.has(positionKey(m.fen))) : -1;
    return { ...l, moves: cut < 0 ? l.moves.slice() : l.moves.slice(0, cut + 1) };
  });
}

/** Whether the engine panel must be neutral for this target: the move is hidden, or its position is a hidden one. */
export function isHiddenTarget({ hidden, mv, hiddenKeys } = {}) {
  if (hidden) return true;
  return !!(mv && hiddenKeys && typeof mv.fen_before === "string" && hiddenKeys.has(positionKey(mv.fen_before)));
}

/** The moves exploring may start from for line i (already cut at a hidden position), or null when it must not. */
export function selectableLine({ resp, i, target, hidden, hiddenKeys } = {}) {
  if (isHiddenTarget({ hidden, mv: target, hiddenKeys })) return null;
  const line = resp && Array.isArray(resp.lines) ? truncateLines(resp.lines, hiddenKeys)[i] : null;
  return line && Array.isArray(line.moves) && line.moves.length > 0 ? line.moves : null;
}

/** Which tab is really shown: Coach while the bar is hidden (guess pending) or analysis is off. */
export function effectiveTab({ saved, hidden, on }) {
  return on && !hidden && saved === "analysis" ? "analysis" : "coach";
}

/**
 * What the bar shows. fill is White's share (0..1); whiteOnTop says which end White's share grows from;
 * labelOnTop says where the score text sits (the leading colour's end; White's end when level).
 */
export function barView({ score, hidden = false, off = false, flipped = false, live = false, dim = false, noGame = false } = {}) {
  const whiteOnTop = !!flipped;
  if (noGame && !off) {
    return { off: false, hidden: false, fill: 0.5, label: "", aria: "No game loaded", dim: false, whiteOnTop,
      labelOn: "white", labelOnTop: whiteOnTop, live: !!live };
  }
  if (off || hidden) {
    return { off: !!off, hidden: !!hidden, fill: 0.5, label: "", aria: hidden ? NEUTRAL_ARIA : "", dim: false,
      whiteOnTop, labelOn: "white", labelOnTop: whiteOnTop, live: !!live };
  }
  const blackLeads = side(score) < 0;
  return {
    off: false, hidden: false, fill: barFill(score), label: barText(score), aria: ariaFor(score),
    dim: !!dim, whiteOnTop, labelOn: blackLeads ? "black" : "white", labelOnTop: blackLeads ? !whiteOnTop : whiteOnTop, live: !!live,
  };
}

export function analysisNote({ hidden, noGame } = {}) {
  if (noGame) return "No game loaded";
  return hidden ? "Hidden until you guess" : "Engine lines for this position will appear here.";
}

/** The Analysis tab: disabled with a neutral title while the moment is hidden. */
export function tabView({ hidden } = {}) {
  return hidden ? { disabled: true, title: "Available after you guess" } : { disabled: false, title: "" };
}

/** Short messages for the one persistent live region (#exploreAnnounce). */
export function exploreAnnouncement({ kind, step, total, san } = {}) {
  if (kind === "enter") return "Exploring a line";
  if (kind === "exit") return "Back to the game";
  if (kind === "step") return `Position ${(step | 0) + 1} of ${total | 0}: ${san}`;
  return "";
}

export function renderBar(el, view) {
  el.hidden = !!view.off;
  el.setAttribute("aria-label", view.aria);
  el.dataset.hidden = String(!!view.hidden);
  el.dataset.whiteTop = String(!!view.whiteOnTop);
  el.dataset.labelTop = String(!!view.labelOnTop);
  el.dataset.labelOn = view.labelOn || "white";
  el.dataset.dim = String(!!view.dim);
  el.style.setProperty("--fill", `${(view.fill * 100).toFixed(1)}%`);
  const label = el.querySelector(".eval-label");
  if (label) label.textContent = view.label;
}

/** Tab buttons are plain toggle buttons (aria-pressed), so Left/Right stay the global step keys. */
export function renderTabs(tabsEl, panels, active) {
  tabsEl.querySelectorAll("button[data-tab]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.tab === active)));
  for (const [name, panel] of Object.entries(panels)) panel.hidden = name !== active;
}

const GAME_OVER = { checkmate: "Checkmate", stalemate: "Stalemate", draw: "Draw" };

/**
 * Pure view-model of the lines panel. state.kind: thinking | loaded | error | gameOver | hidden | noGame.
 * Rows are the engine lines (the badge side says who is ahead; level counts as white); skeleton is the number of
 * placeholder rows; retry says whether to offer a Retry button.
 */
export function linesView(state = {}) {
  const none = { header: "", rows: [], skeleton: 0, note: "", retry: false };
  switch (state.kind) {
    case "hidden": return { ...none, note: analysisNote({ hidden: true }) };
    case "noGame": return { ...none, note: analysisNote({ noGame: true }) };
    case "unavailable": return { ...none, note: "Position unavailable" };
    case "thinking": return { ...none, skeleton: 3, note: "Stockfish is thinking..." };
    case "error": return { ...none, retry: true, note: state.message || "Analysis failed" };
    case "gameOver": return { ...none, note: GAME_OVER[state.result] || "Game over" };
    case "loaded": {
      const r = state.response && typeof state.response === "object" ? state.response : {};
      // The server's version is the engine's own name ("Stockfish 19"); never print the name twice.
      const ver = typeof r.version === "string" ? r.version.trim() : "";
      const parts = [!ver ? "Stockfish" : /^stockfish\b/i.test(ver) ? ver : "Stockfish " + ver];
      if (typeof r.depth === "number" && Number.isFinite(r.depth)) parts.push("depth " + r.depth);
      const lines = Array.isArray(state.lines) ? state.lines : Array.isArray(r.lines) ? r.lines : [];
      const rows = lines.map((l, i) => {
        const text = lineText(state.fen, l && l.moves, 8);
        return { index: i + 1, scoreText: formatScore(l && l.score), badge: side(l && l.score) < 0 ? "black" : "white",
          text, name: lineA11yName(i + 1, l && l.score, text) };
      });
      return { ...none, header: parts.join(" · "), rows, note: rows.length ? "" : "No engine lines for this position." };
    }
    default: return { ...none, note: analysisNote({}) };
  }
}

/**
 * Rebuilds the panel from the view-model (textContent only). handlers.onSelect(i) gets the 0-based line index
 * when a line is clicked; handlers.onRetry() is the Retry button.
 */
export function renderLines(panelEl, state, handlers = {}) {
  const doc = panelEl.ownerDocument;
  const mk = (tag, className, text) => {
    const e = doc.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const v = linesView(state);
  const kids = [];
  if (v.header) kids.push(mk("div", "lines-head", v.header));
  if (v.note) {
    kids.push(mk("div", "note", v.note));  // announced through the persistent #analysisAnnounce, not rebuilt as a live region
  }
  if (v.retry) {
    const b = mk("button", "lines-retry", "Retry");
    b.type = "button";
    b.addEventListener("click", () => handlers.onRetry && handlers.onRetry());
    kids.push(b);
  }
  for (let i = 0; i < v.skeleton; i++) kids.push(mk("div", "line-row skeleton"));
  v.rows.forEach((r, i) => {
    const b = mk("button", "line-row");
    b.type = "button";
    b.setAttribute("aria-label", r.name);
    b.addEventListener("click", () => handlers.onSelect && handlers.onSelect(i));
    b.append(mk("span", "score-badge " + r.badge, r.scoreText), mk("span", "line-moves", r.text));
    kids.push(b);
  });
  panelEl.replaceChildren(...kids);
}

/** Whether the page may ask the engine about this move at all (the neutrality rule lives here). */
export function shouldRequest({ mv, hidden, analysisOn, hiddenKeys } = {}) {
  return !!(analysisOn && mv && !isHiddenTarget({ hidden, mv, hiddenKeys }) && typeof mv.fen_before === "string" && mv.fen_before);
}

/**
 * Which lines state to show. peek(fen) returns the cached response for exactly that FEN (or null);
 * status is the controller's latest { fen, kind, message }, used only when it answers this position.
 */
export function linesState({ mv, hidden, analysisOn = true, peek, status, hiddenKeys } = {}) {
  if (!mv) return { kind: "noGame" };
  if (isHiddenTarget({ hidden, mv, hiddenKeys })) return { kind: "hidden" };
  if (!analysisOn) return { kind: "off" };
  const fen = mv.fen_before;
  if (typeof fen !== "string" || !fen) return { kind: "unavailable" };
  const got = typeof peek === "function" ? peek(fen) : null;
  if (got) return got.game_over ? { kind: "gameOver", fen, result: got.result } : { kind: "loaded", fen, response: got, lines: truncateLines(got.lines, hiddenKeys) };
  if (status && status.fen === fen && status.kind === "error") return { kind: "error", fen, message: status.message };
  return { kind: "thinking", fen };
}

/** The bar's fill is dimmed while the live value is loading or the engine failed (the label is never dimmed). */
export const barDim = (ls) => !!ls && (ls.kind === "thinking" || ls.kind === "error");

/** Pure view of the explore banner; null when there is no path. fen is the REAL game position the path starts from. */
export function bannerView({ fen, path, step } = {}) {
  if (!Array.isArray(path) || !path.length) return null;
  const at = Math.min(Math.max(step | 0, 0), path.length - 1);
  const first = at === 0;
  return { title: "Exploring a line", text: pathWindow(fen, path, at, 8),
    position: `${at + 1} of ${path.length}` + (first ? " \u00b7 \u2039 returns to the game" : ""),
    prevLabel: first ? "Back to the game position" : "Previous position in the line",
    canNext: at < path.length - 1 };
}

/** Rebuilds the banner (textContent only). It is a labelled region, not a live region (see exploreAnnouncement). */
export function renderBanner(el, view, handlers = {}) {
  const doc = el.ownerDocument;
  if (!view) { el.replaceChildren(); el.dataset.active = "false"; return; }
  const mk = (tag, cls, text) => { const e = doc.createElement(tag); if (cls) e.className = cls; e.textContent = text; return e; };
  const btn = (text, label, fn, disabled) => {
    const b = mk("button", "", text); b.type = "button"; b.setAttribute("aria-label", label); b.disabled = !!disabled;
    b.addEventListener("click", fn); return b;
  };
  const hadFocus = el.contains(doc.activeElement) ? doc.activeElement.dataset.role : null;
  el.dataset.active = "true";
  const head = mk("div", "explore-head");
  head.append(mk("strong", "", view.title), mk("span", "explore-pos", view.position));
  const ctl = mk("div", "explore-ctl");
  const prev = btn("\u2039", view.prevLabel, handlers.onPrev);
  const next = btn("\u203a", "Next position in the line", handlers.onNext, !view.canNext);
  prev.dataset.role = "prev"; next.dataset.role = "next";
  const back = btn("Back to the game (Esc)", "Back to the game", handlers.onBack);
  back.dataset.role = "back";
  ctl.append(prev, next, back);
  el.replaceChildren(head, mk("div", "explore-line", view.text), ctl);
  if (hadFocus) { const t = el.querySelector(`[data-role="${hadFocus}"]`); (t && !t.disabled ? t : el.querySelector('[data-role="back"]')).focus(); }
}
