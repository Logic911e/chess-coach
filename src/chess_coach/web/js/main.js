// Theatre page. All text from the server is inserted with textContent, never innerHTML.
import { getGames, getGame, explainMove, guessMove, chatMove, getPlayers } from "./api.js";
import { renderBoard, moveArrows, keyIndex, startIndex, clampIndex, pieceSlides } from "./board.js";
import { motionAllowed } from "./motion.js";
import { createKeyHandler, toggleMute } from "./keys.js";
import { createSettings, settingNeedsRender } from "./settings.js";
import { soundsFor, createPlayer, DEFAULT_VOLUME } from "./sound.js";
import { canGuess, createGuessFlow, guessView, mayWriteExplain } from "./guess.js";
import { createChat, HONESTY_NOTE, FLAG_WARNING } from "./chat.js";
import { resolveMe } from "./me.js";

const state = { me: null, players: [], games: [], game: null, idx: 0, flipped: false, showEngine: true, slides: [],
  guess: { from: null, busy: false, msg: "", kind: "" } };
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
// CSS switches transitions off through data-motion, from the same predicate as the JS animations.
function syncMotion() { if (motionAllowed()) delete root.dataset.motion; else root.dataset.motion = "off"; }
if (window.matchMedia) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (mq.addEventListener) mq.addEventListener("change", syncMotion);
}
function applySettings(changed) {
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
  syncMotion();
  if (state.game && settingNeedsRender(changed)) render();  // arrow colours are read from the theme
}

// ---------- rendering ----------
function labelColors() {
  const c = {};
  for (const k of ["best", "excellent", "good", "inaccuracy", "mistake", "blunder"]) c[k] = css("--" + k);
  return c;
}

// animate: slide pieces and draw arrows in; true only when navigating, never for flip, toggles or settings.
function render(animate = false) {
  const g = state.game; if (!g || !g.moves.length) return;
  const mv = cur();
  const guessing = guessFlow.active();
  renderBoard($("boardWrap"), mv.fen_before, {
    flipped: state.flipped,
    // While guessing, nothing on the board may give the answer away: no arrows, no played-move highlight.
    highlight: guessing ? (state.guess.from ? [state.guess.from] : []) : [mv.uci.slice(0, 2), mv.uci.slice(2, 4)],
    arrows: guessing ? [] : moveArrows(mv, labelColors(), { hideBest: !state.showEngine }),
    slides: state.slides,
    motion: animate,
  });
  state.slides = [];
  $("boardWrap").dataset.guess = guessing ? "on" : "off";

  $("gameTitle").textContent = `${g.white} vs ${g.black} · ${g.result}`;
  $("counter").textContent = `move ${state.idx + 1} of ${g.moves.length}`;
  const view = guessView(mv, guessing);
  $("moveName").textContent = view.heading;
  $("labelPill").replaceChildren(...(view.showPill ? [el("span", { className: "pill " + mv.classification, textContent: mv.classification })] : []));
  $("reasons").replaceChildren(...(view.showReasons ? mv.reasons.map((r) =>
    el("span", { className: "reason", textContent: "key moment: " + r.replace("_", " ") })) : []));
  const bestTxt = mv.best_uci === mv.uci ? "the engine's best move" : `the engine preferred ${mv.best_san}`;
  $("happened").textContent = guessing ? "" :
    `${mv.color === "white" ? g.white : g.black} lost ${mv.expected_points_lost.toFixed(3)} expected points; ${bestTxt}.`;
  renderGuessUi(mv, guessing);
  renderAsk();
  if (!guessing) renderExplain(mv);
  renderStrip();
  $("engineBtn").setAttribute("aria-pressed", String(state.showEngine));
  $("engineBtn").textContent = state.showEngine ? "Hide engine move" : "Show engine move";
  $("prevKey").disabled = keyIndex(g.moves, state.idx, -1) < 0;
  $("nextKey").disabled = keyIndex(g.moves, state.idx, 1) < 0;
  $("first").disabled = $("prev").disabled = state.idx === 0;
  $("last").disabled = $("next").disabled = state.idx === g.moves.length - 1;
}

function renderGuessUi(mv, guessing) {
  const g = state.game, btn = $("guessBtn"), msg = $("guessMsg");
  const can = canGuess(mv, state.me, g), done = guessFlow.resultFor(mv);
  btn.hidden = !can;
  btn.disabled = !can || (!!done && !guessing);
  btn.textContent = guessing ? "Cancel guess" : "Guess first";
  btn.title = done && !guessing ? "One guess per key moment" : "Guess the better move (G)";
  msg.className = "guess-msg" + (guessing && state.guess.kind ? " " + state.guess.kind : "");
  if (guessing) {
    msg.textContent = state.guess.busy ? "Scoring your move with the engine. This can take a few seconds…"
      : state.guess.msg || (state.guess.from ? "Now click where it goes." : "Click the piece you would move.");
    $("explainBox").replaceChildren(el("div", { className: "note", textContent: "The explanation is hidden until you guess." }));
    $("explainAct").replaceChildren();
  } else msg.textContent = done || "";
}

// While a guess is active the chat is off, so an answer (which may name the engine's best move) cannot leak it.
function renderAsk() { $("askBtn").title = "Ask the coach about this position (/)"; }
const GUESS_FIRST = "Finish your guess first.";

// ---------- guess first ----------
const guessFlow = createGuessFlow({
  api: { guessMove },
  ui: {
    enter() { state.guess = { from: null, busy: false, msg: "", kind: "" }; render(); },
    select(sq) { state.guess.from = sq; state.guess.msg = ""; state.guess.kind = ""; if (guessFlow.active()) render(); },
    pending(b) { state.guess.busy = b; if (b) { state.guess.msg = ""; state.guess.kind = ""; } if (guessFlow.active()) render(); },
    message(text, kind) { state.guess.msg = text; state.guess.kind = kind; if (guessFlow.active()) render(); },
    cancelled() { if (state.game) render(); },
    spentAlready() {},
    reveal(mv, result) {
      if (cur() !== mv) return;  // the flow is cancelled on navigation; this is a second guard
      render();
      if (motionAllowed()) {
        player.play(soundsFor({ classification: result.classification }));
        if (result.matched) player.playKeyMoment();
      }
      if (!mv.explanation) explain(mv, false);
    },
  },
});
function startGuess() {
  if (!state.game || !state.game.moves.length || guessFlow.active()) return;
  const mv = cur();
  if (!canGuess(mv, state.me, state.game)) return;
  setChat(false);
  chat.invalidate();  // an answer still in flight could name the best move
  guessFlow.begin(mv);
}
function cancelGuess() { guessFlow.cancel(); }

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
  // A guess hides the explanation: writes from a request in flight are skipped, and the result is
  // cached on the move so render() shows it after the reveal or a cancel.
  if (mayWriteExplain(guessFlow.active())) {
    $("explainAct").replaceChildren();
    box.replaceChildren(el("div", { className: "note", textContent: "Asking the local model…" }));
  }
  try {
    const r = await explainMove(mv.id, regenerate);
    mv.explanation = r.body; mv.explanation_flagged = r.flagged;
  } catch (e) {
    if (cur() === mv) {
      if (!mayWriteExplain(guessFlow.active())) return;
      box.replaceChildren(el("div", { className: "warn", textContent: e.message }));
      const retry = el("button", { type: "button", textContent: mv.explanation ? "Regenerate" : "Explain this move" });
      retry.onclick = () => explain(mv, regenerate);
      $("explainAct").append(retry);
      return;
    }
  }
  if (cur() === mv && mayWriteExplain(guessFlow.active())) renderExplain(mv);
}

function renderStrip() {
  const strip = $("strip"); strip.replaceChildren();
  state.game.moves.forEach((mv, i) => {
    const view = guessView(mv, guessFlow.active() && i === state.idx);
    const b = el("button", { type: "button", title: view.stripTitle });
    b.style.height = Math.max(4, mv.expected_points_lost * 30) + "px";
    if (!view.stripNeutral && !QUIET.includes(mv.classification)) b.style.background = css("--" + mv.classification);
    if (i === state.idx) b.classList.add("cur");
    b.onclick = () => go(i);
    strip.append(b);
  });
}

// ---------- navigation ----------
function go(i) {
  if (!state.game || !state.game.moves.length) return;
  const j = clampIndex(state.game.moves, i);
  const moved = j !== state.idx;
  if (moved) guessFlow.cancel();
  // Slide only single steps (either direction); jumps just redraw.
  state.slides = Math.abs(j - state.idx) === 1 ? pieceSlides(cur().fen_before, state.game.moves[j].fen_before) : [];
  state.idx = j;
  chat.sync();
  render(moved && motionAllowed());
  if (moved && motionAllowed()) player.play(soundsFor(cur()));
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
  for (const id of ["moveName", "labelPill", "reasons", "happened", "guessMsg", "explainBox", "explainAct", "strip"]) $(id).replaceChildren();
  for (const id of ["prevKey", "nextKey", "first", "prev", "next", "last"]) $(id).disabled = true;
}

async function selectGame(id) {
  guessFlow.cancel();
  try { state.game = await getGame(id); }
  catch (e) { $("gameTitle").textContent = "Could not open the game: " + e.message; return; }
  state.idx = startIndex(state.game.moves);
  state.slides = [];
  chat.sync();
  document.querySelectorAll("#gameList button").forEach((b) => b.classList.toggle("sel", Number(b.dataset.id) === id));
  if (!state.game.moves.length) { showEmpty(); return; }
  render();
}

// ---------- overlays ----------
// Modal dialogs (Games, shortcuts) make the page behind them inert, so focus cannot leave them,
// and give focus back to what opened them.
const modalOpen = () => !$("gamesOverlay").hidden || !$("helpOverlay").hidden || !$("meOverlay").hidden;
const returnTo = new Map();  // dialog id -> element that had focus when it opened
function setModal(id, open, first, opener) {
  const ov = $(id), was = !ov.hidden;
  if (open === was) return;
  ov.hidden = !open;
  if (open) {
    returnTo.set(id, document.activeElement);  // read before inert can blur it
    $("topbar").inert = $("stage").inert = true;
    syncDrawerInert();
    first().focus();
  } else {
    $("topbar").inert = $("stage").inert = modalOpen();
    syncDrawerInert();
    const prev = returnTo.get(id);
    returnTo.delete(id);
    const ok = prev && prev !== document.body && prev.isConnected && !prev.disabled;
    (ok ? prev : opener).focus();
  }
}
const setGames = (open) => setModal("gamesOverlay", open,
  () => $("gameList").querySelector("button.sel, button") || $("gamesClose"), $("gamesBtn"));
const setHelp = (open) => setModal("helpOverlay", open, () => $("helpClose"), $("helpBtn"));
const setMe = (open) => setModal("meOverlay", open, () => $("meList").querySelector("button") || $("meClose"), $("helpBtn"));
// The drawer is reachable only when it is open and no modal is on top of it.
function syncDrawerInert() { $("chatDrawer").inert = !$("chatDrawer").classList.contains("open") || modalOpen(); }
function setChat(open, focusInput = false) {
  const d = $("chatDrawer");
  if (open && (guessFlow.active() || !state.game)) return;  // chat.open() reports the guess case
  const hadFocus = d.contains(document.activeElement);
  if (open) chat.sync();
  d.classList.toggle("open", open);
  d.setAttribute("aria-hidden", String(!open));
  syncDrawerInert();
  $("askBtn").setAttribute("aria-expanded", String(open));
  if (open && focusInput) $("chatInput").focus();
  if (!open && hadFocus) $("askBtn").focus();
}

// ---------- chat ----------
const chatStatus = (text, kind = "") => { $("chatStatus").textContent = text; $("chatStatus").className = "chat-status" + (kind ? " " + kind : ""); };
const chat = createChat({
  api: { chatMove },
  getMoveId: () => (state.game && state.game.moves.length ? cur().id : null),
  isBlocked: () => guessFlow.active(),
  ui: {
    open() { setChat(true, true); },
    blocked() { state.guess.msg = GUESS_FIRST; state.guess.kind = ""; if (guessFlow.active()) render(); },
    restore(q) { if (!$("chatInput").value) $("chatInput").value = q; },
    close() { setChat(false); },
    reset() { $("chatLog").replaceChildren(); chatStatus(""); },
    user(text) {
      $("chatLog").append(el("div", { className: "chat-msg user", textContent: text }));
      $("chatInput").value = "";
      scrollChat();
    },
    pending(b) {
      $("chatSend").disabled = b;
      if (b) chatStatus("Asking the local model. This can take up to 30 seconds…", "busy"); else chatStatus("");
    },
    answer(body, flagged) {
      const m = el("div", { className: "chat-msg coach" }, el("div", { textContent: body }));
      if (flagged) m.append(el("div", { className: "warn", textContent: FLAG_WARNING }));
      m.append(el("div", { className: "note", textContent: HONESTY_NOTE }));
      $("chatLog").append(m);
      scrollChat();
    },
    error(msg) { chatStatus(msg, "error"); },
  },
});
function scrollChat() { const l = $("chatLog"); l.scrollTop = l.scrollHeight; }

// ---------- who "me" is ----------
function showMe() {
  const cur = state.me;
  $("meCurrent").textContent = cur ? `Playing as ${cur}.` : "";
  $("changeMe").hidden = !state.players.length;
}
function chooseMe(name) {
  state.me = name;
  settings.set("me", name);
  settings.set("meDismissed", false);
  showMe();
  if (state.game) render();
}
function dismissMe() { settings.set("meDismissed", true); setMe(false); }
function openMePrompt() {
  $("meList").replaceChildren(...state.players.map((p) => {
    const b = el("button", { type: "button", textContent: p.name });
    b.append(el("span", { className: "note", textContent: `  ${p.games} ${p.games === 1 ? "game" : "games"}` }));
    b.onclick = () => { chooseMe(p.name); setMe(false); };
    return el("li", {}, b);
  }));
  setMe(true);
}
async function loadMe() {
  let r;
  try { r = await getPlayers(); } catch (e) { return; }  // guess-first just stays hidden
  state.players = r.players || [];
  const res = resolveMe({ stored: settings.get("me", null), players: state.players, suggested: r.suggested,
    dismissed: settings.get("meDismissed", false) });
  state.me = res.me;
  showMe();
  if (state.game) render();
  if (res.needsPrompt) openMePrompt();
}

// ---------- keyboard ----------
function toggleSoundMute() {
  const r = toggleMute(settings.get("soundPalette", "felt"), settings.get("mutedFrom", undefined));
  if (r.prev) settings.set("mutedFrom", r.prev);
  settings.set("soundPalette", r.palette);
  applySettings("soundPalette");
}
const handleKey = createKeyHandler({
  step: (d) => { if (modalOpen() || !state.game) return false; go(state.idx + d); },
  nextKey: () => { if (modalOpen() || !state.game) return false; goKey(1); },
  prevKey: () => { if (modalOpen() || !state.game) return false; goKey(-1); },
  guess: () => { if (modalOpen()) return false; startGuess(); },
  chat: () => { if (modalOpen() || !state.game) return false; chat.open(); },
  close: () => {
    if (!$("meOverlay").hidden) dismissMe();
    else if (!$("helpOverlay").hidden) setHelp(false);
    else if (!$("gamesOverlay").hidden) setGames(false);
    else if ($("chatDrawer").classList.contains("open")) setChat(false);
    else if (guessFlow.active()) cancelGuess();
    else return false;
  },
  mute: () => { if (modalOpen()) return false; toggleSoundMute(); },
  help: () => { if ($("helpOverlay").hidden && ($("gamesOverlay").hidden === false || $("meOverlay").hidden === false)) return false; setHelp($("helpOverlay").hidden); },
});

async function init() {
  applySettings();
  loadMe();
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
  b.addEventListener("click", () => { settings.set("theme", b.dataset.themeChoice); applySettings("theme"); }));
$("studyToggle").addEventListener("click", () => { settings.set("studyMode", !settings.get("studyMode", false)); applySettings("studyMode"); });
document.querySelectorAll("[data-sound-choice]").forEach((b) =>
  b.addEventListener("click", () => { settings.set("mutedFrom", null); settings.set("soundPalette", b.dataset.soundChoice); applySettings("soundPalette"); }));
$("volume").addEventListener("input", () => { settings.set("volume", Number($("volume").value)); });
// Browsers block audio until a gesture: create the context on the first pointer or key event.
for (const type of ["pointerdown", "pointerup", "click", "touchend", "keydown"]) document.addEventListener(type, () => player.unlock(), { capture: true });
$("first").onclick = () => go(0);
$("last").onclick = () => go(Infinity);
$("prev").onclick = () => go(state.idx - 1);
$("next").onclick = () => go(state.idx + 1);
$("prevKey").onclick = () => goKey(-1);
$("nextKey").onclick = () => goKey(1);
$("guessBtn").onclick = () => { if (guessFlow.active()) cancelGuess(); else startGuess(); };
$("boardWrap").addEventListener("click", (e) => {
  if (modalOpen() || $("chatDrawer").classList.contains("open") || !guessFlow.active()) return;
  const sq = e.target.closest && e.target.closest(".sq");
  if (sq) guessFlow.pick(sq.dataset.sq);  // data-sq is the true square, whatever the orientation
});
$("flip").onclick = () => { state.flipped = !state.flipped; if (state.game) render(); };
$("engineBtn").onclick = () => { state.showEngine = !state.showEngine; if (state.game) render(); };
$("gamesBtn").onclick = () => setGames(true);
$("gamesClose").onclick = () => setGames(false);
$("gamesOverlay").addEventListener("click", (e) => { if (e.target === $("gamesOverlay")) setGames(false); });
$("askBtn").onclick = () => {
  if ($("chatDrawer").classList.contains("open")) setChat(false); else chat.open();
};
$("chatClose").onclick = () => setChat(false);
$("chatForm").addEventListener("submit", (e) => { e.preventDefault(); chat.send($("chatInput").value); });
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); chat.send($("chatInput").value); }
});
$("meClose").onclick = dismissMe;
$("meOverlay").addEventListener("click", (e) => { if (e.target === $("meOverlay")) dismissMe(); });
$("changeMe").onclick = () => { setHelp(false); openMePrompt(); };
document.addEventListener("keydown", (e) => { if (handleKey(e)) e.preventDefault(); });
$("helpBtn").onclick = () => setHelp(true);
$("helpClose").onclick = () => setHelp(false);
$("helpOverlay").addEventListener("click", (e) => { if (e.target === $("helpOverlay")) setHelp(false); });
init();
