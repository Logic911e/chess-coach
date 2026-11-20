"use strict";
// Game review page. All text from the server is inserted with textContent, never innerHTML.
const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
const state = { games: [], game: null, idx: 0, flipped: false };
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  kids.forEach((k) => e.append(k));
  return e;
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* keep statusText */ }
    throw new Error(msg);
  }
  return r.json();
}

// ---------- board ----------
function parseFen(fen) {
  const rows = fen.split(" ")[0].split("/");
  return rows.map((row) => {
    const out = [];
    for (const ch of row) {
      if (/\d/.test(ch)) for (let i = 0; i < +ch; i++) out.push(null);
      else out.push(ch);
    }
    return out; // rows[0] is rank 8
  });
}
const sqName = (file, rankIdx) => "abcdefgh"[file] + (8 - rankIdx);
function sqXY(name) { // centre of a square in the 0..8 SVG space, respecting orientation
  const f = name.charCodeAt(0) - 97, r = 8 - +name[1];
  return state.flipped ? [7 - f + 0.5, 7 - r + 0.5] : [f + 0.5, r + 0.5];
}

function drawBoard(fen, highlight) {
  const grid = parseFen(fen), board = $("board");
  board.replaceChildren();
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const rr = state.flipped ? 7 - r : r, ff = state.flipped ? 7 - f : f;
      const name = sqName(ff, rr), piece = grid[rr][ff];
      const sq = el("div", { className: "sq " + ((ff + rr) % 2 === 0 ? "l" : "d") });
      if (highlight.includes(name)) sq.classList.add("hl");
      if (piece) {
        const white = piece === piece.toUpperCase();
        sq.append(el("span", { className: white ? "w" : "b", textContent: GLYPH[piece.toLowerCase()] }));
      }
      if (f === 0) sq.append(el("i", { className: "r", textContent: String(8 - rr) }));
      if (r === 7) sq.append(el("i", { className: "f", textContent: "abcdefgh"[ff] }));
      board.append(sq);
    }
  }
}

function arrow(svg, uci, color) {
  const [x1, y1] = sqXY(uci.slice(0, 2)), [x2, y2] = sqXY(uci.slice(2, 4));
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
  const head = 0.38, bx = x2 - ux * head, by = y2 - uy * head, w = 0.13;
  const ns = "http://www.w3.org/2000/svg";
  const line = document.createElementNS(ns, "line");
  for (const [k, v] of Object.entries({ x1, y1, x2: bx, y2: by, stroke: color, "stroke-width": 0.18,
                                        "stroke-linecap": "round", opacity: 0.85 })) line.setAttribute(k, v);
  const tip = document.createElementNS(ns, "polygon");
  tip.setAttribute("points", `${x2},${y2} ${bx - uy * w * 2},${by + ux * w * 2} ${bx + uy * w * 2},${by - ux * w * 2}`);
  tip.setAttribute("fill", color); tip.setAttribute("opacity", 0.85);
  svg.append(line, tip);
}

// ---------- rendering ----------
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const m = () => state.game.moves[state.idx];

function render() {
  const g = state.game; if (!g) return;
  const mv = m();
  drawBoard(mv.fen_before, [mv.uci.slice(0, 2), mv.uci.slice(2, 4)]);
  const svg = $("arrows"); svg.replaceChildren();
  if (mv.best_uci !== mv.uci) arrow(svg, mv.uci, css("--" + mv.classification) || "#d23b3b");
  arrow(svg, mv.best_uci, css("--best"));

  const cls = mv.classification;
  const head = $("moveHead"); head.replaceChildren(
    `${mv.move_number}${mv.color === "white" ? "." : "..."} ${mv.san}`,
    el("span", { className: "pill " + cls, textContent: cls }),
    ...mv.reasons.map((r) => el("span", { className: "reason", textContent: "key moment: " + r.replace("_", " ") })));
  const bestTxt = mv.best_uci === mv.uci ? "the engine's best move" : `best was ${mv.best_san}`;
  const legend = $("legend"); legend.replaceChildren(
    `${mv.color === "white" ? g.white : g.black} · lost ${mv.expected_points_lost.toFixed(3)} expected points · ${bestTxt}`);
  if (mv.best_uci !== mv.uci) {
    legend.append(el("span", { className: "arrowkey", style: `background:${css("--" + cls)}` }), "played",
                  el("span", { className: "arrowkey", style: `background:${css("--best")}` }), "best");
  }
  renderExplain(mv);
  renderStrip(); renderMoves();
  $("gameTitle").textContent = `${g.white} vs ${g.black} · ${g.result} · ${g.played_on || ""}`;
  $("prevKey").disabled = keyIndex(-1) < 0; $("nextKey").disabled = keyIndex(1) < 0;
}

function renderExplain(mv) {
  const box = $("explainBox"); box.replaceChildren();
  if (mv.explanation) {
    box.append(el("p", { textContent: mv.explanation }));
    if (mv.explanation_flagged) box.append(el("div", { className: "warn",
      textContent: "The checker flagged this text (an illegal move or a wrong piece square) and it ran out of retries." }));
    box.append(el("div", { className: "note",
      textContent: "Written by a small local model from engine facts. It is checked for legal moves and piece squares only, so it can still contain mistakes." }));
    const again = el("button", { textContent: "Regenerate" });
    again.onclick = () => explain(mv, true); box.append(again);
  } else if (mv.is_key_moment) {
    const b = el("button", { textContent: "Explain this move" });
    b.onclick = () => explain(mv, false); box.append(b);
  } else {
    box.append(el("div", { className: "note",
      textContent: "Not a key moment, so there is no explanation. Key moments are mistakes, blunders, big swings and brilliant finds." }));
  }
}

async function explain(mv, regenerate) {
  const box = $("explainBox"); box.replaceChildren(el("div", { className: "note", textContent: "Asking the local model…" }));
  try {
    const r = await api(`/api/moves/${mv.id}/explain?regenerate=${regenerate}`, { method: "POST" });
    mv.explanation = r.body; mv.explanation_flagged = r.flagged;
  } catch (e) {
    if (m() === mv) { box.replaceChildren(el("div", { className: "warn", textContent: e.message })); return; }
  }
  if (m() === mv) renderExplain(mv);
}

function renderStrip() {
  const strip = $("strip"); strip.replaceChildren();
  state.game.moves.forEach((mv, i) => {
    const b = el("button", { title: `${mv.move_number}${mv.color === "white" ? "." : "..."} ${mv.san} (${mv.classification})` });
    b.style.height = Math.max(4, mv.expected_points_lost * 54) + "px";
    b.style.background = mv.classification === "best" || mv.classification === "excellent" || mv.classification === "good"
      ? "var(--line)" : css("--" + mv.classification);
    if (i === state.idx) b.classList.add("cur");
    b.onclick = () => go(i); strip.append(b);
  });
}

function renderMoves() {
  const box = $("moves"); box.replaceChildren();
  const rows = new Map();
  state.game.moves.forEach((mv, i) => {
    if (!rows.has(mv.move_number)) rows.set(mv.move_number, {});
    rows.get(mv.move_number)[mv.color] = [mv, i];
  });
  for (const [n, r] of rows) {
    box.append(el("div", { className: "n", textContent: n + "." }));
    for (const color of ["white", "black"]) {
      if (!r[color]) { box.append(el("div")); continue; }
      const [mv, i] = r[color];
      const b = el("button", { textContent: mv.san }); if (i === state.idx) b.classList.add("cur");
      if (!["best", "excellent", "good"].includes(mv.classification))
        b.append(el("span", { className: "dot " + mv.classification, title: mv.classification }));
      b.onclick = () => go(i); box.append(b);
    }
  }
  box.querySelector(".cur")?.scrollIntoView({ block: "nearest" });
}

// ---------- navigation ----------
function go(i) {
  state.idx = Math.max(0, Math.min(state.game.moves.length - 1, i)); render();
}
function keyIndex(dir) {
  const ms = state.game.moves;
  for (let i = state.idx + dir; i >= 0 && i < ms.length; i += dir) if (ms[i].is_key_moment) return i;
  return -1;
}

async function selectGame(id) {
  state.game = await api("/api/games/" + id);
  const first = state.game.moves.findIndex((x) => x.is_key_moment);
  state.idx = first >= 0 ? first : 0;
  document.querySelectorAll("#gameList button").forEach((b) => b.classList.toggle("sel", +b.dataset.id === id));
  render();
}

async function init() {
  try { state.games = await api("/api/games"); }
  catch (e) { $("gameTitle").textContent = "Cannot reach the database: " + e.message; return; }
  const list = $("gameList");
  for (const g of state.games) {
    const b = el("button", { textContent: `${g.white} vs ${g.black}` });
    b.dataset.id = g.id;
    b.append(el("div", { className: "meta",
      textContent: `${g.result} · ${g.played_on || "?"} · ${g.errors} ${g.errors === 1 ? 'error' : 'errors'}, ${g.key_moments} key` }));
    b.onclick = () => selectGame(g.id); list.append(el("li", {}, b));
  }
  if (state.games.length) selectGame(state.games[0].id);
}

$("first").onclick = () => go(0); $("last").onclick = () => go(1e9);
$("prev").onclick = () => go(state.idx - 1); $("next").onclick = () => go(state.idx + 1);
$("prevKey").onclick = () => { const i = keyIndex(-1); if (i >= 0) go(i); };
$("nextKey").onclick = () => { const i = keyIndex(1); if (i >= 0) go(i); };
$("flip").onclick = () => { state.flipped = !state.flipped; render(); };
document.addEventListener("keydown", (e) => {
  if (!state.game || e.target.tagName === "BUTTON" && e.key === " ") return;
  if (e.key === "ArrowLeft") go(state.idx - 1); else if (e.key === "ArrowRight") go(state.idx + 1);
});
init();
