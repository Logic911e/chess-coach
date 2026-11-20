// Guess-first flow. Imports cleanly in node (no window/document); the page supplies `api` and `ui`.
// No chess logic here: legality and scoring are the server's. The only board reading is the piece
// letter at the source square, to add the queen letter when a pawn reaches the last rank.
import { parseFen } from "./board.js";

const FILES = "abcdefgh";
const PHRASE = {
  best: "the best move", excellent: "an excellent move", good: "a good move",
  inaccuracy: "an inaccuracy", mistake: "a mistake", blunder: "a blunder", brilliant: "a brilliant move",
};

/** A key moment whose mover is "me". */
export function canGuess(move, me, game) {
  if (!move || !game || !me || !move.is_key_moment) return false;
  const mover = move.color === "white" ? game.white : game.black;
  return mover === me;
}

export function revealLine(r) {
  if (r.matched) return `Your guess: ${r.san} matched the engine's move.`;
  const what = PHRASE[r.classification] || `a ${r.classification} move`;
  const lost = Number(r.expected_points_lost || 0).toFixed(2);
  return `Your guess: ${r.san}, ${what}, lost ${lost}. Engine: ${r.best_san}`;
}

/** Piece letter on a square of a FEN, or null. */
export function pieceAt(fen, sq) {
  const row = parseFen(fen)[8 - Number(sq[1])];
  return row ? row[FILES.indexOf(sq[0])] : null;
}

/**
 * What the page may show about the current move. While guessing nothing may reveal its quality or the
 * move played: neutral heading, no pill, no reasons, neutral strip bar and tooltip.
 */
export function guessView(move, guessing) {
  const san = `${move.move_number}${move.color === "white" ? "." : "..."} ${move.san}`;
  if (guessing) return { heading: `Move ${move.move_number} · your move`, showPill: false, showReasons: false,
    stripNeutral: true, stripTitle: "your move" };
  return { heading: san, showPill: true, showReasons: true, stripNeutral: false,
    stripTitle: `${san} (${move.classification})` };
}

/**
 * Accessible name of a move for the move list and strip bars. While it is the current move of an
 * active guess it must not reveal the move or its label.
 */
export function moveA11yName(move, guessing) {
  if (guessing) return `Move ${move.move_number}, your move`;
  return `${move.move_number}${move.color === "white" ? "." : "..."} ${move.san}, ${move.classification}`;
}

/** An in-flight explain() may touch the explanation box only outside a guess. */
export const mayWriteExplain = (guessing) => !guessing;

function toUci(fen, from, to) {
  const piece = pieceAt(fen, from);
  const last = (piece === "P" && to[1] === "8") || (piece === "p" && to[1] === "1");
  return from + to + (last ? "q" : "");
}

/**
 * ui: enter(move), select(square|null), pending(bool), message(text), reveal(move, result, line),
 * cancelled(). The attempt is spent only when the server says legal: true.
 */
export function createGuessFlow({ api, ui }) {
  const results = new Map();  // move id -> reveal line (one attempt per move per visit)
  let cur = null;             // { move, from, busy, token }
  let counter = 0;

  return {
    active: () => cur !== null,
    resultFor: (move) => (move && results.has(move.id) ? results.get(move.id) : null),
    begin(move) {
      if (results.has(move.id)) { ui.spentAlready(move, results.get(move.id)); return false; }
      cur = { move, from: null, busy: false, token: ++counter };
      ui.enter(move);
      return true;
    },
    cancel() {
      if (!cur) return;
      cur = null; counter++;
      ui.cancelled();
    },
    async pick(square) {
      if (!cur || cur.busy) return;
      const g = cur;
      if (g.from === null) {
        if (!pieceAt(g.move.fen_before, square)) return;  // nothing to pick up
        g.from = square; ui.select(square); return;
      }
      if (g.from === square) { g.from = null; ui.select(null); return; }
      const uci = toUci(g.move.fen_before, g.from, square);
      g.busy = true; ui.pending(true);
      let r, err = null;
      try { r = await api.guessMove(g.move.id, uci); } catch (e) { err = e; }
      if (cur !== g) return;  // cancelled or moved away while scoring: paint nothing
      g.busy = false; g.from = null; ui.pending(false); ui.select(null);
      if (err) { ui.message(err.message || "Could not score the guess.", "error"); return; }
      if (!r.legal) { ui.message("That is not a legal move here. Try another.", "gentle"); return; }
      const line = revealLine(r);
      results.set(g.move.id, line);
      cur = null;
      ui.reveal(g.move, r, line);
    },
  };
}
