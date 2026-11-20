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
  return Math.max(0, Math.min(moves.length - 1, i));  // empty game: 0
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
 * Pieces that moved between two positions, for the slide animation. Rule: a square that gains a
 * piece P is matched with a square that lost the same piece P (first match); the piece slides from
 * the lost square to the gained one. This is direction-agnostic (works stepping back too), covers
 * captures (the captured piece just vanishes) and castling (king and rook both slide), and leaves
 * unmatched changes such as promotions to appear without sliding.
 */
export function pieceSlides(fenFrom, fenTo) {
  const a = parseFen(fenFrom), b = parseFen(fenTo), lost = [], gained = [];
  for (let r = 0; r < 8; r++) for (let f = 0; f < 8; f++) {
    if (a[r][f] === b[r][f]) continue;
    const name = FILES[f] + (8 - r);
    if (a[r][f]) lost.push({ name, piece: a[r][f] });
    if (b[r][f]) gained.push({ name, piece: b[r][f] });
  }
  const out = [];
  for (const g of gained) {
    const i = lost.findIndex((l) => l.piece === g.piece);
    if (i >= 0) { out.push({ from: lost[i].name, to: g.name }); lost.splice(i, 1); }
  }
  return out;
}

/**
 * Draw the position into `el` (replaces its children). `slides` ({from, to}[], see pieceSlides)
 * animate pieces sliding in, and the arrows fade in, only when `motion` is true (the caller passes
 * motionAllowed()). Replacing the children cancels any animation still running: nothing queues.
 */
export function renderBoard(el, fen, { flipped = false, highlight = [], arrows = [], slides = [], motion = false } = {}) {
  const grid = parseFen(fen);
  const board = document.createElement("div");
  board.className = "board-grid";
  board.setAttribute("role", "img");
  board.setAttribute("aria-label", "Chess board");
  const imgs = new Map();
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
        imgs.set(name, img);
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

  if (!motion) return;
  const size = board.getBoundingClientRect().width / 8;
  for (const { from, to } of slides) {
    const img = imgs.get(to);
    if (!img || typeof img.animate !== "function") continue;
    const [x1, y1] = squareXY(from, flipped), [x2, y2] = squareXY(to, flipped);
    img.animate([{ transform: `translate(${(x1 - x2) * size}px, ${(y1 - y2) * size}px)` },
                 { transform: "translate(0, 0)" }], { duration: 200, easing: "ease-out" });
  }
  if (arrows.length && typeof svg.animate === "function") {
    svg.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: "ease-out" });
  }
}
