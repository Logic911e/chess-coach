// Board module. The pure helpers import cleanly in node (no window/document at import time);
// only renderBoard touches the DOM, and only when called.
const FILES = "abcdefgh";
const SVG_NS = "http://www.w3.org/2000/svg";

/** FEN placement field -> 8 rows (rank 8 first) of piece letters or null. */
export function parseFen(fen) {
  return fen.split(" ")[0].split("/").map((row) => {
    const out = [];
    for (const ch of row) {
      if (ch >= "0" && ch <= "9") for (let i = 0; i < Number(ch); i++) out.push(null);
      else out.push(ch);
    }
    return out;
  });
}

/** Centre of a square in the 0..8 SVG space, respecting orientation. */
export function squareXY(name, flipped) {
  const f = name.charCodeAt(0) - 97, r = 8 - Number(name[1]);
  return flipped ? [7 - f + 0.5, 7 - r + 0.5] : [f + 0.5, r + 0.5];
}

/** Arrows for a move: the played move in its label colour, the engine's in green; one if equal. */
export function moveArrows(mv, colors, { hideBest = false } = {}) {
  const out = [];
  if (mv.best_uci !== mv.uci) out.push({ uci: mv.uci, color: colors[mv.classification] || colors.blunder || "#d23b3b" });
  if (!hideBest) out.push({ uci: mv.best_uci, color: colors.best });
  return out;
}

/** Index of the next key moment in direction dir (+1/-1) from idx, or -1. */
export function keyIndex(moves, idx, dir) {
  for (let i = idx + dir; i >= 0 && i < moves.length; i += dir) if (moves[i].is_key_moment) return i;
  return -1;
}

/** Where a freshly opened game starts: its first key moment, else the first move. */
export function startIndex(moves) {
  const i = moves.findIndex((m) => m.is_key_moment);
  return i >= 0 ? i : 0;
}

export function clampIndex(moves, i) {
  return Math.max(0, Math.min(moves.length - 1, i));
}

function svgArrow(svg, uci, color, flipped) {
  const [x1, y1] = squareXY(uci.slice(0, 2), flipped), [x2, y2] = squareXY(uci.slice(2, 4), flipped);
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
  const head = 0.38, bx = x2 - ux * head, by = y2 - uy * head, w = 0.13;
  const line = document.createElementNS(SVG_NS, "line");
  for (const [k, v] of Object.entries({ x1, y1, x2: bx, y2: by, stroke: color, "stroke-width": 0.18,
                                        "stroke-linecap": "round", opacity: 0.85 })) line.setAttribute(k, v);
  const tip = document.createElementNS(SVG_NS, "polygon");
  tip.setAttribute("points", `${x2},${y2} ${bx - uy * w * 2},${by + ux * w * 2} ${bx + uy * w * 2},${by - ux * w * 2}`);
  tip.setAttribute("fill", color);
  tip.setAttribute("opacity", 0.85);
  svg.append(line, tip);
}

/**
 * Draw the position into `el` (replaces its children). animateFrom is an optional UCI move whose
 * piece slides from the source to the destination square (skipped in study mode / reduced motion).
 */
export function renderBoard(el, fen, { flipped = false, highlight = [], arrows = [], animateFrom } = {}) {
  const grid = parseFen(fen);
  const board = document.createElement("div");
  board.className = "board-grid";
  board.setAttribute("role", "img");
  board.setAttribute("aria-label", "Chess board");
  let slide = null;
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const rr = flipped ? 7 - r : r, ff = flipped ? 7 - f : f;
      const name = FILES[ff] + (8 - rr), piece = grid[rr][ff];
      const sq = document.createElement("div");
      sq.className = "sq " + ((ff + rr) % 2 === 0 ? "l" : "d");
      sq.dataset.sq = name;
      if (highlight.includes(name)) sq.classList.add("hl");
      if (piece) {
        const white = piece === piece.toUpperCase();
        const img = document.createElement("img");
        img.src = `/static/pieces/${white ? "w" : "b"}${piece.toUpperCase()}.svg`;
        img.alt = (white ? "white " : "black ") + piece.toLowerCase();
        img.draggable = false;
        sq.append(img);
        if (animateFrom && name === animateFrom.slice(2, 4)) slide = img;
      }
      if (f === 0) { const i = document.createElement("i"); i.className = "r"; i.textContent = String(8 - rr); sq.append(i); }
      if (r === 7) { const i = document.createElement("i"); i.className = "f"; i.textContent = FILES[ff]; sq.append(i); }
      board.append(sq);
    }
  }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "arrows");
  svg.setAttribute("viewBox", "0 0 8 8");
  svg.setAttribute("aria-hidden", "true");
  for (const a of arrows) svgArrow(svg, a.uci, a.color, flipped);
  el.replaceChildren(board, svg);

  if (slide && animateFrom && typeof slide.animate === "function" && motionAllowed()) {
    const [x1, y1] = squareXY(animateFrom.slice(0, 2), flipped), [x2, y2] = squareXY(animateFrom.slice(2, 4), flipped);
    const size = board.getBoundingClientRect().width / 8;
    slide.animate([{ transform: `translate(${(x1 - x2) * size}px, ${(y1 - y2) * size}px)` },
                   { transform: "translate(0, 0)" }], { duration: 220, easing: "ease-out" });
  }
}

function motionAllowed() {
  if (document.documentElement.dataset.study === "on") return false;
  return !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}
