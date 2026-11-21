// Evaluation bar and tabs. barView is pure; the render adapters touch the DOM only inside their bodies.
import { barFill, barLabel, formatScore } from "./analysis.js";

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

/**
 * What the bar shows. fill is White's share (0..1); whiteOnTop says which end White's share grows from;
 * labelOnTop says where the score text sits (the leading colour's end; White's end when level).
 */
export function barView({ score, hidden = false, off = false, flipped = false, live = false, dim = false } = {}) {
  const whiteOnTop = !!flipped;
  if (off || hidden) {
    return { off: !!off, hidden: !!hidden, fill: 0.5, label: "", aria: hidden ? NEUTRAL_ARIA : "", dim: false,
      whiteOnTop, labelOnTop: false, live: !!live };
  }
  const blackLeads = side(score) < 0;
  return {
    off: false, hidden: false, fill: barFill(score), label: barLabel(score), aria: ariaFor(score),
    dim: !!dim, whiteOnTop, labelOnTop: blackLeads ? !whiteOnTop : whiteOnTop, live: !!live,
  };
}

export function analysisNote({ hidden }) {
  return hidden ? "Hidden until you guess" : "Engine lines for this position will appear here.";
}

export function renderBar(el, view) {
  el.hidden = !!view.off;
  el.setAttribute("aria-label", view.aria);
  el.dataset.hidden = String(!!view.hidden);
  el.dataset.whiteTop = String(!!view.whiteOnTop);
  el.dataset.labelTop = String(!!view.labelOnTop);
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
