// Chat drawer logic. Imports cleanly in node (no window/document); the page supplies `api` and `ui`.
// History is kept per move and dropped when the move changes; the server uses only the last few turns.
export const HONESTY_NOTE =
  "Checked for legal moves and piece squares only, so it can still contain mistakes.";
export const FLAG_WARNING = "This answer failed the move and square check. Treat it with caution.";
export const GUESS_NOTICE = "Finish your guess first.";
const MAX_QUESTION = 1000, MAX_TURNS = 20, MAX_TURN_CHARS = 2000;

/**
 * ui: open(), close(), reset(), user(text), pending(bool), answer(body, flagged), error(msg), notice(msg).
 * getMoveId(): id of the move on screen. isBlocked(): true while a guess is active.
 */
export function createChat({ api, ui, getMoveId, isBlocked = () => false }) {
  let moveId = getMoveId();
  let history = [];
  let token = 0;
  let busy = false;

  // Called on every move change (and before every send): drops history and invalidates any request in flight.
  function sync() {
    const now = getMoveId();
    if (now === moveId) return;
    moveId = now; history = []; token++;
    if (busy) { busy = false; ui.pending(false); }
    ui.reset();
  }

  async function send(text) {
    sync();
    if (busy) return false;
    const question = String(text == null ? "" : text).trim();
    if (!question) return false;
    if (isBlocked()) { ui.notice(GUESS_NOTICE); return false; }
    if (question.length > MAX_QUESTION) { ui.error(`Questions can be at most ${MAX_QUESTION} characters.`); return false; }
    const id = moveId, mine = ++token;
    busy = true;
    ui.user(question);
    ui.pending(true);
    try {
      const r = await api.chatMove(id, question, history.slice(-MAX_TURNS));
      if (mine !== token || getMoveId() !== id) return false;  // the user has left this move
      history.push({ role: "user", content: question },
        { role: "assistant", content: String(r.body).slice(0, MAX_TURN_CHARS) });
      history = history.slice(-MAX_TURNS);
      busy = false; ui.pending(false);
      ui.answer(r.body, !!r.flagged);
      return true;
    } catch (e) {
      if (mine !== token || getMoveId() !== id) return false;
      busy = false; ui.pending(false);
      ui.error((e && e.message) || "The chat failed.");
      return false;
    }
  }

  return {
    open() { sync(); ui.open(); },
    close() { ui.close(); },
    send,
    sync,
    busy: () => busy,
  };
}
