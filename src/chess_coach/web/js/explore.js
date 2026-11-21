// Exploring mode state machine. Pure: no window/document. The path is a list of the server's line moves
// ({ san, uci, fen, capture, check }); step indexes the current one (the position AFTER that move).
const validLine = (m) => Array.isArray(m) && m.length > 0 && m.every((x) => x && typeof x.fen === "string" && x.fen);

/** Exploring may start only on a visible moment, with analysis on and a line to walk (the neutrality rule). */
export const canExplore = ({ hidden, analysisOn, hasLines } = {}) => !!analysisOn && !hidden && !!hasLines;

export function createExplore() {
  let path = [];
  let step = -1;
  const clear = () => { path = []; step = -1; };
  const active = () => step >= 0;
  const position = () => (active() ? { fen: path[step].fen, move: path[step], step } : null);

  return {
    begin(lineMoves) {
      if (!validLine(lineMoves)) return;  // junk leaves the state unchanged
      path = lineMoves.slice();
      step = 0;
    },
    /** Keep the path up to the current step, append the line, continue after its first move. */
    extend(lineMoves) {
      if (!active() || !validLine(lineMoves)) return;
      path = path.slice(0, step + 1).concat(lineMoves);
      step += 1;
    },
    /** +1 / -1. Returns { moved: true, move } | { exited: true } | null (nothing to do). */
    step(dir) {
      if (!active()) return null;
      if (dir > 0) {
        if (step >= path.length - 1) return null;
        step += 1;
        return { moved: true, move: path[step] };
      }
      if (step === 0) { clear(); return { exited: true }; }
      step -= 1;
      return { moved: true, move: path[step] };
    },
    exit: clear,
    active,
    position,
    path: () => path.slice(),
    atStart: () => step === 0,
  };
}
