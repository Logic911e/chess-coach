// Theatre page. All text from the server is inserted with textContent, never innerHTML.
import { getGames, getGame, explainMove } from "./api.js";
import { renderBoard, moveArrows, keyIndex, startIndex, clampIndex } from "./board.js";
import { createSettings } from "./settings.js";
import { soundsFor, createPlayer, DEFAULT_VOLUME } from "./sound.js";

const state = { games: [], game: null, idx: 0, flipped: false, showEngine: true, animateFrom: undefined };
const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const QUIET = ["best", "excellent", "good"];

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  kids.forEach((k) => e.append(k));
  return e;
}
const css = (n) => getComputedStyle(root).getPropertyValue(n).trim();
const cur = () => state.game.moves[state.idx];
const label = (mv) => `${mv.move_number}${mv.color === "white" ? "." : "..."} ${mv.san}`;

// ---------- settings (theme, study mode) ----------
let store; try { store = window.localStorage; } catch (e) { store = undefined; }
const settings = createSettings(store);
window.chessCoachSettings = settings;
const player = createPlayer({ settings, audioContextFactory: () => new (window.AudioContext || window.webkitAudioContext)() });
window.chessCoachPlayer = player;
const reducedMotion = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
function applySettings() {
  const theme = settings.get("theme", "walnut");
  root.dataset.theme = theme;
  document.querySelectorAll("[data-theme-choice]")
    .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === theme)));
  const on = settings.get("studyMode", false);
  if (on) root.dataset.study = "on"; else delete root.dataset.study;
  $("studyToggle").setAttribute("aria-pressed", String(on));
  const pal = settings.get("soundPalette", "felt");
  document.querySelectorAll("[data-sound-choice]")
    .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.soundChoice === pal)));
  $("volume").value = String(settings.get("volume", DEFAULT_VOLUME));
  if (state.game) render();  // arrow colours are read from the theme
}

// ---------- rendering ----------
function labelColors() {
  const c = {};
  for (const k of ["best", "excellent", "good", "inaccuracy", "mistake", "blunder"]) c[k] = css("--" + k);
  return c;
}

function render() {
  const g = state.game; if (!g || !g.moves.length) return;
  const mv = cur();
  renderBoard($("boardWrap"), mv.fen_before, {
    flipped: state.flipped,
    highlight: [mv.uci.slice(0, 2), mv.uci.slice(2, 4)],
    arrows: moveArrows(mv, labelColors(), { hideBest: !state.showEngine }),
    animateFrom: state.animateFrom,
  });
  state.animateFrom = undefined;

  $("gameTitle").textContent = `${g.white} vs ${g.black} · ${g.result}`;
  $("counter").textContent = `move ${state.idx + 1} of ${g.moves.length}`;
  $("moveName").textContent = label(mv);
  $("labelPill").replaceChildren(el("span", { className: "pill " + mv.classification, textContent: mv.classification }));
  $("reasons").replaceChildren(...mv.reasons.map((r) =>
    el("span", { className: "reason", textContent: "key moment: " + r.replace("_", " ") })));
  const bestTxt = mv.best_uci === mv.uci ? "the engine's best move" : `the engine preferred ${mv.best_san}`;
  $("happened").textContent =
    `${mv.color === "white" ? g.white : g.black} lost ${mv.expected_points_lost.toFixed(3)} expected points; ${bestTxt}.`;
  renderExplain(mv);
  renderStrip();
  $("engineBtn").setAttribute("aria-pressed", String(state.showEngine));
  $("engineBtn").textContent = state.showEngine ? "Hide engine move" : "Show engine move";
  $("prevKey").disabled = keyIndex(g.moves, state.idx, -1) < 0;
  $("nextKey").disabled = keyIndex(g.moves, state.idx, 1) < 0;
  $("first").disabled = $("prev").disabled = state.idx === 0;
  $("last").disabled = $("next").disabled = state.idx === g.moves.length - 1;
}

const HONESTY = "Written by a small local model from engine facts. It is checked for legal moves and piece squares only, so it can still contain mistakes.";

function renderExplain(mv) {
  const box = $("explainBox"), act = $("explainAct");
  box.replaceChildren(); act.replaceChildren();
  if (mv.explanation) {
    box.append(el("p", { className: "explain-text", textContent: mv.explanation }));
    if (mv.explanation_flagged) box.append(el("div", { className: "warn",
      textContent: "The checker flagged this text (an illegal move or a wrong piece square) and it ran out of retries." }));
    box.append(el("div", { className: "note", textContent: HONESTY }));
    const again = el("button", { type: "button", textContent: "Regenerate" });
    again.onclick = () => explain(mv, true);
    act.append(again);
  } else if (mv.is_key_moment) {
    const b = el("button", { type: "button", textContent: "Explain this move" });
    b.onclick = () => explain(mv, false);
    act.append(b);
  } else {
    box.append(el("div", { className: "note", textContent:
      "Not a key moment, so there is no explanation. Key moments are mistakes, blunders, big swings and brilliant finds." }));
  }
}

async function explain(mv, regenerate) {
  const box = $("explainBox");
  $("explainAct").replaceChildren();
  box.replaceChildren(el("div", { className: "note", textContent: "Asking the local model…" }));
  try {
    const r = await explainMove(mv.id, regenerate);
    mv.explanation = r.body; mv.explanation_flagged = r.flagged;
  } catch (e) {
    if (cur() === mv) {
      box.replaceChildren(el("div", { className: "warn", textContent: e.message }));
      const retry = el("button", { type: "button", textContent: mv.explanation ? "Regenerate" : "Explain this move" });
      retry.onclick = () => explain(mv, regenerate);
      $("explainAct").append(retry);
      return;
    }
  }
  if (cur() === mv) renderExplain(mv);
}

function renderStrip() {
  const strip = $("strip"); strip.replaceChildren();
  state.game.moves.forEach((mv, i) => {
    const b = el("button", { type: "button", title: `${label(mv)} (${mv.classification})` });
    b.style.height = Math.max(4, mv.expected_points_lost * 30) + "px";
    if (!QUIET.includes(mv.classification)) b.style.background = css("--" + mv.classification);
    if (i === state.idx) b.classList.add("cur");
    b.onclick = () => go(i);
    strip.append(b);
  });
}

// ---------- navigation ----------
function go(i) {
  if (!state.game || !state.game.moves.length) return;
  const j = clampIndex(state.game.moves, i);
  state.animateFrom = j === state.idx + 1 ? state.game.moves[state.idx].uci : undefined;
  const moved = j !== state.idx;
  state.idx = j;
  render();
  if (moved && !reducedMotion()) player.play(soundsFor(cur()));
}
function goKey(dir) {
  if (!state.game || !state.game.moves.length) return;
  const i = keyIndex(state.game.moves, state.idx, dir);
  if (i >= 0) go(i);
}

function showEmpty() {
  $("gameTitle").textContent = "This game has no moves";
  $("counter").textContent = "";
  $("boardWrap").replaceChildren();
  for (const id of ["moveName", "labelPill", "reasons", "happened", "explainBox", "explainAct", "strip"]) $(id).replaceChildren();
  for (const id of ["prevKey", "nextKey", "first", "prev", "next", "last"]) $(id).disabled = true;
}

async function selectGame(id) {
  try { state.game = await getGame(id); }
  catch (e) { $("gameTitle").textContent = "Could not open the game: " + e.message; return; }
  state.idx = startIndex(state.game.moves);
  state.animateFrom = undefined;
  document.querySelectorAll("#gameList button").forEach((b) => b.classList.toggle("sel", Number(b.dataset.id) === id));
  if (!state.game.moves.length) { showEmpty(); return; }
  render();
}

// ---------- overlays ----------
function setGames(open) {
  const was = !$("gamesOverlay").hidden;
  $("gamesOverlay").hidden = !open;
  if (!open && !was) return;
  if (open) $("gameList").querySelector("button.sel, button")?.focus(); else $("gamesBtn").focus();
}
function setChat(open) {
  const d = $("chatDrawer");
  d.classList.toggle("open", open);
  d.setAttribute("aria-hidden", String(!open));
  d.inert = !open;
  $("askBtn").setAttribute("aria-expanded", String(open));
}

async function init() {
  applySettings();
  try { state.games = await getGames(); }
  catch (e) { $("gameTitle").textContent = "Cannot reach the database: " + e.message; return; }
  const list = $("gameList");
  for (const g of state.games) {
    const b = el("button", { type: "button", textContent: `${g.white} vs ${g.black}` });
    b.dataset.id = g.id;
    b.append(el("div", { className: "meta",
      textContent: `${g.result} · ${g.played_on || "?"} · ${g.errors} ${g.errors === 1 ? "error" : "errors"}, ${g.key_moments} key` }));
    b.onclick = () => { setGames(false); selectGame(g.id); };
    list.append(el("li", {}, b));
  }
  if (state.games.length) selectGame(state.games[0].id);
  else $("gameTitle").textContent = "No games imported yet";
}

document.querySelectorAll("[data-theme-choice]").forEach((b) =>
  b.addEventListener("click", () => { settings.set("theme", b.dataset.themeChoice); applySettings(); }));
$("studyToggle").addEventListener("click", () => { settings.set("studyMode", !settings.get("studyMode", false)); applySettings(); });
document.querySelectorAll("[data-sound-choice]").forEach((b) =>
  b.addEventListener("click", () => { settings.set("soundPalette", b.dataset.soundChoice); applySettings(); }));
$("volume").addEventListener("input", () => { settings.set("volume", Number($("volume").value)); });
// Browsers block audio until a gesture: create the context on the first pointer or key event.
for (const type of ["pointerdown", "keydown"]) document.addEventListener(type, () => player.unlock(), { capture: true });
$("first").onclick = () => go(0);
$("last").onclick = () => go(Infinity);
$("prev").onclick = () => go(state.idx - 1);
$("next").onclick = () => go(state.idx + 1);
$("prevKey").onclick = () => goKey(-1);
$("nextKey").onclick = () => goKey(1);
$("flip").onclick = () => { state.flipped = !state.flipped; if (state.game) render(); };
$("engineBtn").onclick = () => { state.showEngine = !state.showEngine; if (state.game) render(); };
$("gamesBtn").onclick = () => setGames(true);
$("gamesClose").onclick = () => setGames(false);
$("gamesOverlay").addEventListener("click", (e) => { if (e.target === $("gamesOverlay")) setGames(false); });
$("askBtn").onclick = () => setChat(!$("chatDrawer").classList.contains("open"));
$("chatClose").onclick = () => setChat(false);
$("chatForm").addEventListener("submit", (e) => e.preventDefault());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { setGames(false); setChat(false); return; }
  if (!state.game || e.target.tagName === "INPUT" || !$("gamesOverlay").hidden) return;
  if (e.key === "ArrowLeft") go(state.idx - 1); else if (e.key === "ArrowRight") go(state.idx + 1);
});
init();
