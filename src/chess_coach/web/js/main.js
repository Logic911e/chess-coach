// Theatre page. All text from the server is inserted with textContent, never innerHTML.
import { getGames, getGame, explainMove, guessMove, chatMove, getPlayers, analysePosition } from "./api.js";
import { renderBoard, moveArrows, keyIndex, startIndex, clampIndex, pieceSlides, boardFen } from "./board.js";
import { motionAllowed } from "./motion.js";
import { createKeyHandler, toggleMute, escapeTarget, stepAction } from "./keys.js";
import { createExplore, canExplore } from "./explore.js";
import { createLatest } from "./latest.js";
import { createSettings, settingNeedsRender } from "./settings.js";
import { soundsFor, createPlayer, DEFAULT_VOLUME } from "./sound.js";
import { explainBlocks, fieldsNote } from "./explain-view.js";
import { canGuess, createGuessFlow, guessView, mayWriteExplain, moveA11yName, isHidden, stripBarHeight } from "./guess.js";
import { createChat, HONESTY_NOTE, FLAG_WARNING } from "./chat.js";
import { resolveMe, settleWithin } from "./me.js";
import { scoreFromStored, createAnalysis, gameOverScore } from "./analysis.js";
import { barView, renderBar, renderTabs, effectiveTab, renderLines, linesState, shouldRequest, barDim, bannerView, renderBanner, tabView, exploreAnnouncement, linesView, hiddenPositionKeys, isHiddenTarget, selectableLine, shouldExitExplore, focusTarget, linePlyCounts } from "./analysis-ui.js";

const state = { me: null, players: [], games: [], game: null, idx: 0, flipped: false, showEngine: false, slides: [],
  guess: { from: null, busy: false, msg: "", kind: "" } };
const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const QUIET = ["best", "excellent", "good"];
const answered = new Set();  // move ids whose answer the user chose to see this visit (not persisted)
// Neutral until the user has guessed or chosen "Show the answer" (also true during an active guess).
const hiddenNow = (mv) => isHidden(mv, state.me, state.game, guessFlow, answered);
// Positions the engine panel must never reach or pass: the position before every hidden move of the WHOLE game
// (recomputed on every use, never cached, so a guess or "Show the answer" takes effect at once).
const hiddenKeys = () => hiddenPositionKeys(state.game ? state.game.moves : [], hiddenNow);

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
  renderAnalysisChrome();
  if (state.game && settingNeedsRender(changed)) render();  // arrow colours are read from the theme
}

// ---------- analysis bar and tabs (logic in analysis-ui.js) ----------
const analysisOn = () => settings.get("analysis", true);
// Live analysis: the controller debounces, caches and discards stale answers; these callbacks only record the
// status of the CURRENT request and redraw. A cached answer is read back with analysis.peek.
let liveStatus = { fen: null, kind: "idle", message: "" };
const analysis = createAnalysis({
  api: { analysePosition },
  ui: {
    thinking(fen) { liveStatus = { fen, kind: "thinking", message: "" }; drawAnalysis(); },
    loaded(fen) { liveStatus = { fen, kind: "loaded", message: "" }; drawAnalysis(); },
    gameOver(fen) { liveStatus = { fen, kind: "gameOver", message: "" }; drawAnalysis(); },
    error(fen, message) { liveStatus = { fen, kind: "error", message }; drawAnalysis(); },
    busyDim() { drawAnalysis(); },  // the bar already stays dimmed while thinking; nothing is shown for a busy engine
  },
});
let shownLines = null;
// Exploring mode (state machine in explore.js). While it is active the board, bar and lines follow the explored FEN;
// everything else (caption, chat, Explain) stays about the real game move.
const explore = createExplore();
let lastScore;  // what the bar last showed: kept (dimmed) while an explored position is still loading
// The position the board shows for a move: after it by default, before it at a guess or with "Show engine move".
const shownFen = (mv) => boardFen(mv, { hidden: hiddenNow(mv), showEngine: state.showEngine });
// The position the engine panel is about: the explored one, else the one the board shows.
const analysisTarget = (mv) => { const p = explore.position(); return p ? { fen_before: p.fen } : mv ? { fen_before: shownFen(mv) } : mv; };
function renderAnalysisChrome() {
  const g = state.game, mv = g && g.moves.length ? cur() : null;
  // Asks only when analysis is on and the move is not hidden (no request at all at a guess); a repeat is a no-op.
  const t = analysisTarget(mv);
  analysis.request(t ? t.fen_before : null, { enabled: shouldRequest({ mv: t, hidden: !!mv && hiddenNow(mv), analysisOn: analysisOn(),
    hiddenKeys: hiddenKeys() }) });
  drawAnalysis();
}
function drawAnalysis() {
  const on = analysisOn();
  if (on) delete root.dataset.analysis; else root.dataset.analysis = "off";
  $("analysisToggle").setAttribute("aria-pressed", String(on));
  $("capTabs").hidden = !on;
  const g = state.game, mv = g && g.moves.length ? cur() : null;
  const hidden = !!mv && hiddenNow(mv);
  const keys = hiddenKeys(), target = analysisTarget(mv);
  // The bar and lines are neutral for the hidden move AND for any position that is a hidden one (an explored line's end,
  // a transposition); the tab and the coach panel follow the real move only.
  const neutral = !!target && isHiddenTarget({ hidden, mv: target, hiddenKeys: keys });
  // While a guess is pending the Coach panel (with the guess controls) is shown whatever tab is saved;
  // the saved choice is untouched and returns once the answer is shown.
  renderTabs($("capTabs"), { coach: $("coachPanel"), analysis: $("analysisPanel") },
    effectiveTab({ saved: settings.get("analysisTab", "coach"), hidden, on }));
  const tv = tabView({ hidden });
  $("tabAnalysis").disabled = tv.disabled;
  $("tabAnalysis").title = tv.title;
  // A disabled button drops focus to body; hidden tabs cannot hold it either (analysis just switched off).
  if (document.activeElement && $("capTabs").contains(document.activeElement) && ($("capTabs").hidden || (hidden && document.activeElement === $("tabAnalysis")))) focusTabs();
  const pos = explore.position();
  const ls = linesState({ mv: target, hidden, analysisOn: on, peek: analysis.peek, status: liveStatus, hiddenKeys: keys });
  // The stored value (position BEFORE the selected move, White's perspective) shows until the live top line arrives;
  // while loading only the fill is dimmed.
  const liveResp = ls.kind === "loaded" ? ls.response : null;
  const top = liveResp && liveResp.lines && liveResp.lines[0];
  // The stored value matches the position on the board: after the move it is the move's own score, before it the best one.
  const onAfter = !!mv && shownFen(mv) !== mv.fen_before;
  let score = top ? top.score : mv ? scoreFromStored(onAfter ? mv.cp_played : mv.cp_best, mv.color) : undefined;
  if (pos && !top) score = ls.kind === "gameOver" ? gameOverScore(ls.result, ls.fen) : lastScore;  // only live values apply
  lastScore = score;
  renderBar($("evalBar"), barView({ score, hidden: neutral, off: !on, flipped: state.flipped, live: !!top,
    dim: barDim(ls), noGame: !mv }));
  // Rebuild only when something changed, so a render() for an unrelated reason cannot drop focus from a line.
  const k = [ls.kind, ls.fen, ls.message, ls.result, ls.response, linePlyCounts(ls.lines).join()];
  if (shownLines && k.every((v, i) => v === shownLines[i])) return;
  shownLines = k;
  const panel = $("analysisPanel"), hadFocus = panel.contains(document.activeElement);
  renderLines(panel, ls, { onSelect: selectLine, onRetry: () => analysis.retry() });
  // Status notes go through one persistent live region (the panel itself is rebuilt); only while the panel is shown,
  // and "thinking" stays silent because it would repeat on every step.
  const shown = effectiveTab({ saved: settings.get("analysisTab", "coach"), hidden, on }) === "analysis";
  if (shown && ls.kind !== "thinking") say("analysisAnnounce", linesView(ls).note);
  if (hadFocus && !panel.contains(document.activeElement)) {  // a rebuilt line lost focus: keep it near the lines
    const b = panel.querySelector("button.line-row");
    if (b) b.focus(); else focusTabs();
  }
}
function setAnalysis(on) {
  settings.set("analysis", on);
  if (!on) { analysis.invalidate(); if (exitExplore()) return; }
  renderAnalysisChrome();
}

// ---------- exploring a line ----------
function playBase(m) { if (motionAllowed()) player.play(soundsFor({ capture: m.capture, check: m.check })); }
// Click (or Enter) on engine line i: start exploring it, or continue from the current explored step.
function selectLine(i) {
  const g = state.game;
  if (!g || !g.moves.length || modalOpen()) return;
  const t = analysisTarget(cur());
  // Cut at a hidden position and refused from one, so exploring can never go past the answer to a guess.
  const moves = selectableLine({ resp: analysis.peek(t.fen_before), i, target: t, hidden: hiddenNow(cur()), hiddenKeys: hiddenKeys() });
  if (!canExplore({ hidden: false, analysisOn: analysisOn(), hasLines: !!moves })) return;
  const before = t.fen_before, wasExploring = explore.active();
  if (wasExploring) explore.extend(moves); else explore.begin(moves);
  if (!explore.active()) return;
  state.slides = pieceSlides(before, explore.position().fen);
  render(motionAllowed());
  const at = explore.position();
  say("exploreAnnounce", wasExploring
    ? exploreAnnouncement({ kind: "step", step: at.step, total: explore.path().length, san: at.move.san })
    : exploreAnnouncement({ kind: "enter" }));
  playBase(at.move);
}
// Persistent polite live regions: their text is replaced in place, never rebuilt, so a screen reader reads each change once.
function say(id, text) { const a = $(id); if (a.textContent !== text) a.textContent = text; }
// The one way out of exploring: clears the state, announces it and redraws the REAL game position (old game when
// a game switch is pending). render:false lets the caller (go) draw; refocus moves focus to a stable control.
function exitExplore({ render: redraw = true, slides = [], animate = false, refocus = false } = {}) {
  if (!explore.active()) return false;
  const inBanner = $("exploreBanner").contains(document.activeElement);
  explore.exit();
  state.slides = slides;
  say("exploreAnnounce", exploreAnnouncement({ kind: "exit" }));
  if (redraw && state.game && state.game.moves.length) render(animate);
  if (refocus || inBanner) focusTabs();
  return true;
}
// A stable control near the tabs: the Analysis tab, else Coach, else the toggle when the tabs are hidden (analysis off).
function focusTabs() {
  const tabs = $("capTabs");
  const t = focusTarget({ tabsHidden: tabs.hidden, analysisDisabled: $("tabAnalysis").disabled });
  $(t === "toggle" ? "analysisToggle" : t === "analysis" ? "tabAnalysis" : "tabCoach").focus();
}
function exploreStep(d) {
  const before = explore.position().fen;
  if (d < 0 && explore.atStart()) {  // one step back from the first explored position leaves the line
    exitExplore({ slides: pieceSlides(before, shownFen(cur())), animate: motionAllowed() });
    const prevMv = state.game.moves[state.idx - 1]; if (prevMv) playBase(prevMv);
    return;
  }
  const r = explore.step(d);
  if (!r) return;
  state.slides = pieceSlides(before, explore.position().fen);
  render(motionAllowed());
  say("exploreAnnounce", exploreAnnouncement({ kind: "step", step: explore.position().step, total: explore.path().length, san: r.move.san }));
  playBase(r.move);
}
function leaveExplore(refocus = false) { exitExplore({ refocus }); }
function setTab(tab) { settings.set("analysisTab", tab); renderAnalysisChrome(); }

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
  const hidden = hiddenNow(mv);
  if (hidden || !analysisOn()) explore.exit();  // nothing explored may survive a neutral moment or analysis being off
  // A path may end at a hidden position but never pass through one (me or the answers may have changed since it began).
  if (shouldExitExplore({ exploring: explore.active(), path: explore.path(), hiddenKeys: hiddenKeys(),
    hiddenSelected: isHiddenTarget({ hidden, mv, hiddenKeys: hiddenKeys() }) })) {
    exitExplore({ render: false });
  }
  const xp = explore.position();
  renderBoard($("boardWrap"), xp ? xp.fen : shownFen(mv), xp ? {
    flipped: state.flipped, highlight: [xp.move.uci.slice(0, 2), xp.move.uci.slice(2, 4)], arrows: [],
    slides: state.slides, motion: animate,
  } : {
    flipped: state.flipped,
    // Until the user guesses or asks, nothing on the board may give the answer away: no arrows, no played-move highlight.
    highlight: hidden ? (guessing && state.guess.from ? [state.guess.from] : []) : [mv.uci.slice(0, 2), mv.uci.slice(2, 4)],
    // Arrows start from the position before the move, so they appear only with "Show engine move" (which shows that position).
    arrows: hidden || !state.showEngine ? [] : moveArrows(mv, labelColors(), { hideBest: false }),
    slides: state.slides,
    motion: animate,
  });
  state.slides = [];
  renderBanner($("exploreBanner"), xp ? bannerView({ fen: shownFen(mv), path: explore.path(), step: xp.step }) : null,
    { onPrev: () => exploreStep(-1), onNext: () => exploreStep(1), onBack: () => leaveExplore(true) });
  $("boardWrap").dataset.guess = guessing ? "on" : "off";

  $("gameTitle").textContent = `${g.white} vs ${g.black} · ${g.result}`;
  $("counter").textContent = `move ${state.idx + 1} of ${g.moves.length}`;
  const view = guessView(mv, hidden);
  $("moveName").textContent = view.heading;
  $("labelPill").replaceChildren(...(view.showPill ? [el("span", { className: "pill " + mv.classification, textContent: mv.classification })] : []));
  $("reasons").replaceChildren(...(view.showReasons ? mv.reasons.map((r) =>
    el("span", { className: "reason", textContent: "key moment: " + r.replace("_", " ") })) : []));
  const bestTxt = mv.best_uci === mv.uci ? "the engine's best move" : `the engine preferred ${mv.best_san} for ${mv.color === "white" ? "White" : "Black"}`;
  $("happened").textContent = hidden ? "" :
    `${mv.color === "white" ? g.white : g.black} lost ${mv.expected_points_lost.toFixed(3)} expected points; ${bestTxt}.`;
  renderGuessUi(mv, guessing, hidden);
  renderAsk();
  if (!hidden) renderExplain(mv);
  renderStrip();
  renderMoveList();
  renderAnalysisChrome();
  $("engineBtn").setAttribute("aria-pressed", String(state.showEngine));  // one signal: static label + pressed state
  $("engineBtn").disabled = hidden;  // it would give the answer away
  $("engineBtn").title = hidden ? "Available once you have guessed or shown the answer" : "";
  $("prevKey").disabled = keyIndex(g.moves, state.idx, -1) < 0;
  $("nextKey").disabled = keyIndex(g.moves, state.idx, 1) < 0;
  $("first").disabled = $("prev").disabled = state.idx === 0;
  $("last").disabled = $("next").disabled = state.idx === g.moves.length - 1;
}

function renderGuessUi(mv, guessing, hidden) {
  const g = state.game, btn = $("guessBtn"), msg = $("guessMsg"), form = $("guessForm"), input = $("guessInput");
  const can = canGuess(mv, state.me, g), done = guessFlow.resultFor(mv);
  btn.hidden = !can;
  const shown = answered.has(mv.id);
  btn.disabled = !can || (!!done && !guessing) || (shown && !guessing);
  btn.textContent = guessing ? "Cancel guess" : "Guess first";
  btn.title = shown && !guessing ? "You have already seen the answer" : done && !guessing ? "One guess per key moment" : "Guess the better move (G)";
  $("showAnswerBtn").hidden = !(hidden && !guessing);
  // Focus must not be lost when the typed-move field disappears (Esc, reveal).
  const hadFocus = form.contains(document.activeElement);
  form.hidden = !guessing;
  if (!guessing) {
    input.value = "";
    if (hadFocus) (btn.disabled || btn.hidden ? $("engineBtn") : btn).focus();
  }
  input.disabled = guessing && state.guess.busy;
  msg.className = "guess-msg" + (guessing && state.guess.kind ? " " + state.guess.kind : "");
  if (hidden) {
    $("explainBox").replaceChildren(el("div", { className: "note", textContent: guessing
      ? "The explanation is hidden until you guess." : "The explanation is hidden until you guess or show the answer." }));
    $("explainAct").replaceChildren();
  }
  if (guessing) {
    msg.textContent = state.guess.busy ? "Scoring your move with the engine. This can take a few seconds…"
      : state.guess.msg || (state.guess.from ? "Now click where it goes." : "Click the piece you would move, or type it below.");
  } else msg.textContent = hidden ? "Your key moment. Guess the better move first, or show the answer." : done || "";
}

// While a guess is active the chat is off, so an answer (which may name the engine's best move) cannot leak it.
function renderAsk() { $("askBtn").title = "Ask the coach about this position (/)"; }
const GUESS_FIRST = "Finish your guess first.";

// ---------- guess first ----------
const guessFlow = createGuessFlow({
  api: { guessMove },
  ui: {
    enter() { state.guess = { from: null, busy: false, msg: "", kind: "" }; render(); $("guessInput").focus(); },
    select(sq) { state.guess.from = sq; state.guess.msg = ""; state.guess.kind = ""; if (guessFlow.active()) render(); },
    pending(b) { state.guess.busy = b; if (b) { state.guess.msg = ""; state.guess.kind = ""; }
      if (guessFlow.active()) { render(); if (!b && document.activeElement === document.body) $("guessInput").focus(); } },
    message(text, kind) { state.guess.msg = text; state.guess.kind = kind; if (guessFlow.active()) render(); },
    cancelled() { if (state.game) render(); },
    spentAlready() {},
    reveal(mv, result) {
      if (cur() !== mv) return;  // the flow is cancelled on navigation; this is a second guard
      render();
      if (document.activeElement === document.body) focusAfterReveal();  // the disabled field lost focus
      if (motionAllowed()) {
        // One call: sound.js drops a second play in the same tick, which would swallow the key sound.
        player.play([...soundsFor({ classification: result.classification }).slice(1), ...(result.matched ? ["key"] : [])]);
      }
      if (!mv.explanation) explain(mv, false);
    },
  },
});
// After a reveal the Coach panel may be hidden (saved tab is Analysis): focus the visible tab button instead.
function focusAfterReveal() { $("engineBtn").focus(); if (document.activeElement !== $("engineBtn")) focusTabs(); }
function startGuess() {
  if (!state.game || !state.game.moves.length || guessFlow.active()) return;
  const mv = cur();
  if (!canGuess(mv, state.me, state.game) || answered.has(mv.id)) return;
  explore.exit();  // (cannot normally be exploring here: exploring needs an unhidden move)
  setChat(false);
  chat.invalidate();  // an answer still in flight could name the best move
  analysis.invalidate();  // and so could the engine lines
  guessFlow.begin(mv);
}
function cancelGuess() { guessFlow.cancel(); }
function showAnswer() {
  if (!state.game || !state.game.moves.length || guessFlow.active()) return;
  const mv = cur();
  if (!hiddenNow(mv)) return;
  answered.add(mv.id);
  render();
  if (motionAllowed()) {  // the base sound already played on arrival; add the label's cue
    const cue = soundsFor(mv).slice(1);
    if (cue.length) player.play(cue);
  }
  focusAfterReveal();  // the button that was pressed has just gone
}

const HONESTY = "Written by a small local model from engine facts. Moves, piece squares and tactical claims such as \"undefended\" or \"attacks\" are checked against the board. Strategy and reasons are not, so it can still contain mistakes.";

function renderExplain(mv) {
  const box = $("explainBox"), act = $("explainAct");
  box.replaceChildren(); act.replaceChildren();
  if (mv.explanation) {
    // Written in fields: the verdict, why, and what was better each get their own line. An older text is one block.
    for (const b of explainBlocks(mv.explanation_fields, mv.explanation)) {
      box.append(el("p", { className: "explain-text" }, ...(b.label ? [el("strong", { textContent: b.label + ": " })] : []), b.text));
    }
    if (mv.explanation_flagged) box.append(el("div", { className: "warn",
      textContent: "The checker flagged this text (an illegal move, a wrong piece square or a false tactical claim) and it ran out of retries." }));
    if (mv.explanation_current === false) box.append(el("div", { className: "warn",
      textContent: "Written by an earlier version of the coach. Regenerate to update it." }));
    const n = mv.explanation_checked_claims;
    const fromFacts = fieldsNote(mv.explanation_fields);
    box.append(el("div", { className: "note", textContent: (n
      ? `${n} tactical claim${n === 1 ? "" : "s"} checked against the board. ${HONESTY}`
      : `No tactical claims in this text could be checked against the board. ${HONESTY}`) + (fromFacts ? " " + fromFacts : "") }));
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
  // A hidden (not yet guessed) move hides the explanation: writes from a request in flight are skipped, and the result is
  // cached on the move so render() shows it after the reveal or a cancel.
  if (mayWriteExplain(hiddenNow(mv))) {
    $("explainAct").replaceChildren();
    box.replaceChildren(el("div", { className: "note", textContent: "Asking the local model…" }));
  }
  try {
    const r = await explainMove(mv.id, regenerate);
    mv.explanation = r.body; mv.explanation_flagged = r.flagged;
    mv.explanation_checked_claims = r.checked_claims; mv.explanation_current = r.current !== false;
    mv.explanation_fields = r.fields;
  } catch (e) {
    if (cur() === mv) {
      if (!mayWriteExplain(hiddenNow(mv))) return;
      box.replaceChildren(el("div", { className: "warn", textContent: e.message }));
      const retry = el("button", { type: "button", textContent: mv.explanation ? "Regenerate" : "Explain this move" });
      retry.onclick = () => explain(mv, regenerate);
      $("explainAct").append(retry);
      return;
    }
  }
  if (cur() === mv && mayWriteExplain(hiddenNow(mv))) renderExplain(mv);
}

// Rebuilding a list drops focus; put it back on the current item when it was inside the list.
function refocus(container, hadFocus) {
  if (hadFocus) { const c = container.querySelector("[aria-current]"); if (c) c.focus(); }
}

// The strip is one tab stop (roving tabindex: only the current bar is focusable by Tab).
function renderStrip() {
  const strip = $("strip"), hadFocus = strip.contains(document.activeElement);
  strip.replaceChildren();
  state.game.moves.forEach((mv, i) => {
    const guessing = i === state.idx && hiddenNow(mv);
    const view = guessView(mv, guessing);
    const b = el("button", { type: "button", title: view.stripTitle, tabIndex: i === state.idx ? 0 : -1 });
    b.setAttribute("aria-label", moveA11yName(mv, guessing));
    if (i === state.idx) b.setAttribute("aria-current", "step");
    b.style.height = stripBarHeight(view, mv.expected_points_lost) + "px";
    if (!view.stripNeutral && !QUIET.includes(mv.classification)) b.style.background = css("--" + mv.classification);
    if (i === state.idx) b.classList.add("cur");
    b.onclick = () => go(i);
    strip.append(b);
  });
  refocus(strip, hadFocus);
}

// Visually hidden move list for screen readers; shown as a chip while one of its buttons has focus.
function renderMoveList() {
  const list = $("moveList"), hadFocus = list.contains(document.activeElement);
  list.replaceChildren(...state.game.moves.map((mv, i) => {
    const b = el("button", { type: "button", tabIndex: i === state.idx ? 0 : -1,
      textContent: moveA11yName(mv, i === state.idx && hiddenNow(mv)) });
    if (i === state.idx) b.setAttribute("aria-current", "step");
    b.onclick = () => go(i);
    return el("li", {}, b);
  }));
  refocus(list, hadFocus);
}

// ---------- navigation ----------
function go(i) {
  if (!state.game || !state.game.moves.length) return;
  const j = clampIndex(state.game.moves, i);
  const moved = j !== state.idx;
  const wasExploring = exitExplore({ render: false });  // any game navigation returns to the real position first
  if (moved) guessFlow.cancel();
  // Slide only single steps (either direction); jumps just redraw.
  state.slides = !wasExploring && Math.abs(j - state.idx) === 1 ? pieceSlides(shownFen(cur()), shownFen(state.game.moves[j])) : [];
  state.idx = j;
  chat.sync();
  render(moved && motionAllowed());
  // A hidden move only gets its base sound: the best/blunder cue would give the answer away.
  if (moved && motionAllowed()) player.play(soundsFor(hiddenNow(cur()) ? { capture: cur().capture, check: cur().check } : cur()));
}
function goKey(dir) {
  if (!state.game || !state.game.moves.length) return;
  const i = keyIndex(state.game.moves, state.idx, dir);
  if (i >= 0) go(i); else if (explore.active()) go(state.idx);
}

function showEmpty() {
  $("gameTitle").textContent = "This game has no moves";
  $("counter").textContent = "";
  $("boardWrap").replaceChildren();
  for (const id of ["moveName", "labelPill", "reasons", "happened", "guessMsg", "explainBox", "explainAct", "strip", "moveList"]) $(id).replaceChildren();
  for (const id of ["prevKey", "nextKey", "first", "prev", "next", "last"]) $(id).disabled = true;
  renderAnalysisChrome();
}

const gameSeq = createLatest();  // two quick switches can resolve out of order: only the newest selection is applied
async function selectGame(id) {
  exitExplore();  // redraw the real (old) game now, so no explored board or dead banner outlives the await or a failure
  guessFlow.cancel();
  analysis.invalidate();
  let got;
  try { got = await gameSeq.track(getGame(id)); }
  catch (e) { $("gameTitle").textContent = "Could not open the game: " + e.message; return; }
  if (got.stale) return;
  state.game = got.value;
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
      scrollToStart(m);  // a long answer is read from its beginning; focus is not moved
      announce(flagged ? `${body} ${FLAG_WARNING}` : body);
    },
    error(msg) { chatStatus(msg, "error"); },
  },
});
function scrollChat() { const l = $("chatLog"); l.scrollTop = l.scrollHeight; }
function scrollToStart(m) {
  const l = $("chatLog");
  l.scrollTop += m.getBoundingClientRect().top - l.getBoundingClientRect().top;
}
// Only the assistant's answers are announced (the log itself is not a live region); errors go through #chatStatus.
let announceTimer, announceDelay;
function announce(text) {
  const a = $("chatAnnounce");
  clearTimeout(announceDelay); clearTimeout(announceTimer);
  a.textContent = "";
  announceDelay = setTimeout(() => { a.textContent = text; }, 50);
  announceTimer = setTimeout(() => { a.textContent = ""; }, 4000);
}

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
  step: (d) => {
    if (modalOpen() || !state.game) return false;
    if (stepAction({ exploring: explore.active() }) === "explore") exploreStep(d); else go(state.idx + d);
  },
  nextKey: () => { if (modalOpen() || !state.game) return false; goKey(1); },
  prevKey: () => { if (modalOpen() || !state.game) return false; goKey(-1); },
  guess: () => { if (modalOpen()) return false; startGuess(); },
  chat: () => { if (modalOpen() || !state.game) return false; chat.open(); },
  close: () => {
    const t = escapeTarget({ modal: modalOpen(), drawer: $("chatDrawer").classList.contains("open"),
      guess: guessFlow.active(), exploring: explore.active() });
    if (t === "modal") {
      if (!$("meOverlay").hidden) dismissMe();
      else if (!$("helpOverlay").hidden) setHelp(false);
      else setGames(false);
    } else if (t === "drawer") setChat(false);
    else if (t === "guess") cancelGuess();
    else if (t === "explore") leaveExplore();
    else return false;
  },
  mute: () => { if (modalOpen()) return false; toggleSoundMute(); },
  analysis: () => { if (modalOpen()) return false; setAnalysis(!analysisOn()); },
  help: () => { if ($("helpOverlay").hidden && ($("gamesOverlay").hidden === false || $("meOverlay").hidden === false)) return false; setHelp($("helpOverlay").hidden); },
});

async function init() {
  state.me = settings.get("me", null);  // the stored name applies at once; loadMe() confirms it against the players
  applySettings();
  const meReady = loadMe();  // never rejects
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
  // The first game must not render before "me" is known (a key moment would show unhidden and ask the engine);
  // a slow or failed players request must not block the page for long: it then stays in hidden-off behaviour.
  await settleWithin(meReady, 3000);
  if (state.games.length) selectGame(state.games[0].id);
  else $("gameTitle").textContent = "No games imported yet";
}

document.querySelectorAll("[data-theme-choice]").forEach((b) =>
  b.addEventListener("click", () => { settings.set("theme", b.dataset.themeChoice); applySettings("theme"); }));
$("analysisToggle").addEventListener("click", () => setAnalysis(!analysisOn()));
$("tabCoach").addEventListener("click", () => setTab("coach"));
$("tabAnalysis").addEventListener("click", () => setTab("analysis"));
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
$("showAnswerBtn").onclick = showAnswer;
$("guessForm").addEventListener("submit", (e) => { e.preventDefault(); guessFlow.typed($("guessInput").value); });
$("guessBtn").onclick = () => { if (guessFlow.active()) cancelGuess(); else startGuess(); };
$("boardWrap").addEventListener("click", (e) => {
  if (modalOpen() || $("chatDrawer").classList.contains("open") || !guessFlow.active()) return;
  const sq = e.target.closest && e.target.closest(".sq");
  if (sq) guessFlow.pick(sq.dataset.sq);  // data-sq is the true square, whatever the orientation
});
$("flip").onclick = () => { state.flipped = !state.flipped; if (state.game) render(); };
// A link to the stats page beside "Games", made here so the board page's markup and styles are unchanged.
const statsBtn = el("button", { type: "button", id: "statsBtn", textContent: "Stats", title: "Your stats across all stored games" });
statsBtn.onclick = () => { location.href = "/stats" + (state.me ? "?player=" + encodeURIComponent(state.me) : ""); };
$("gamesBtn").after(statsBtn);
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
