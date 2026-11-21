# Analysis bar and clickable engine lines: design

Status: implemented (2026-11-22); see docs/superpowers/plans/2026-11-20-analysis-bar.md. Date: 2026-11-20.

## Intent and why

The review page already shows the move played and the engine's best move for a key moment, but not the engine's
view of a position: how much each side is ahead, and what the best continuations are. The owner (a student
building a portfolio chess coach) wants the Chess.com-style analysis experience: an evaluation bar beside the
board and a panel of the engine's top lines with scores in pawns ("points"), where clicking a line walks the board
through it and you can step back out to the real game.

In the owner's words: the bar and the lines should "show by how much each side is winning (the points) just like
the chess.com one"; it must be toggleable; a slightly busier screen is fine; "clicking a line should walk you
through it on the board. then you should be able to reverse to the current position."

Reference: a Chess.com analysis screenshot (vertical bar left of the board filling from White's side with the score
printed on it; right panel with three lines, each `+0.20  5... Nxb4 6. Rb1 ...`; opening name; move list; navigation
buttons). The owner picked layout option "A · Tabs": the right column switches between **Coach** and **Analysis**.

## Goals

- An **evaluation bar** to the left of the board: fills from White's side (bottom when White is at the bottom),
  flips with the board, prints the score on it (`+0.4`, `-1.2`, `M3`), changes smoothly.
- An **Analysis tab** in the right column (next to the existing **Coach** content): header showing the engine
  name/version and search depth; **three lines**, each with a White-perspective score badge and the first several
  moves in SAN (truncated with an ellipsis; the full line is available on focus/hover and to screen readers).
- **Clickable lines**: clicking a line enters **exploring mode** on that line: the board shows the position after
  its first move and the user can step forward and back through the line (arrow keys, clicking a move in the line,
  or on-screen buttons). The bar and the three lines update for each position reached. A banner shows the line being
  explored and a **"Back to the game" (Esc)** action returns to the exact real-game position and view.
- A **toggle** for the whole analysis feature in the top bar (default **on**; key `a`), remembered in settings.
- Scores in **pawns**: centipawns / 100 with two decimals in the lines (`+0.20`), one decimal on the bar (`+0.4`),
  positive = White ahead, negative = Black ahead; forced mate as `M<n>` (`M3` = White mates in 3, `-M3` = Black).
- All chess work stays on the server: the page never computes legality or positions; every position it shows comes
  from the server as a FEN.

## Non-goals (this version)

- The coach persona / prompt work and "a comment on every move": separate pieces of work, brainstormed later.
- Opening names (the imported games carry none), a full visible move list, free play or dragging pieces from an
  explored position, saving or exporting lines, engine settings (threads, hash, depth picker), multiple engines.
- Streaming / progressively deepening analysis (possible follow-up if the delay feels slow).
- Changing the import depth or re-analysing stored games; no schema changes.
- Mobile-first design.

## Anti-goals (a failure even if it technically works)

- The bar or lines revealing the answer to a **guess**: at a guessable key moment the page hides the engine's answer
  until the user guesses or presses "Show the answer"; the bar and lines must stay hidden then too, and **no engine
  request may be made while hidden** (so neither the content nor the timing leaks).
- A slow or stuck analysis blocking the shared engine so that guessing or chat hang. Analysis requests are bounded in
  time and in size.
- Losing the user's place: after exploring a line and returning, the game position, selected move, flip state and
  view must be exactly as before; nothing explored may leak into the real game state.
- A bar that flickers or jumps wildly between the stored and live values.
- Claiming more precision than the engine has: the depth is shown and scores are Stockfish at limited depth.

## Constraints

- Existing system and stack stay: FastAPI (`src/chess_coach/api.py`), python-chess, Stockfish via the shared
  `EngineService` (`src/chess_coach/engine_service.py`, one analysis at a time behind a lock; its `analyse(board,
  depth, multipv=1)` does not currently accept a time limit although `Engine.analyse` does), plain HTML/CSS/ES modules
  in `src/chess_coach/web/` with no build step and no new library, Postgres unchanged.
- The page does no chess logic. Pure view-state and formatting helpers (score to text, bar fill, line truncation,
  exploring-mode state) live in node-testable modules like the existing `guess.js` / `chat.js`.
- Engine scores from `Engine.analyse` are from the **mover's** perspective (mate capped at +/-`MATE_CP` = 10 000 in
  `cp_capped`); the API must convert to **White's** perspective. Stored per-move evaluations (`cp_best` for the
  position before a move, mover's perspective, depth 14 by default) are capped mate values with no mate distance.
- Server error pattern from guess/chat: engine failures give 503 with a message, anything else is logged and a plain
  500; bounded inputs give 422. `Engine.analyse` raises `ValueError` for a game-over position.
- Accessibility, sound and motion rules from the immersive UI spec still apply: `prefers-reduced-motion` and study
  mode remove motion (the bar's smooth transition included) and sound; contrast >= 4.5:1 in all three themes; no
  `innerHTML` with server text; honesty about what has not been verified.
- Theme tokens (`css/themes.css`) are reused; the bar and score badges must read well in Walnut, Slate and Paper.

## Approaches considered

1. **On demand, one request per position (chosen).** `POST /api/analysis {fen, depth?, lines?}` returns three lines
   with scores and per-ply positions; the page asks again for each position it reaches while exploring; answers are
   cached (server per FEN, page per FEN). The bar shows the stored evaluation instantly, then the live one. Reuses the
   shared engine and needs no schema change. Cost: about 1 to 2 seconds before lines appear; each step in a line
   waits for its own analysis.
2. **Streaming progressive analysis (Chess.com-like).** Lines refine as the engine deepens, over SSE/WebSocket, with
   cancellation when the position changes. Feels most alive; needs engine cancellation so it cannot block guess/chat,
   a streaming API and a more complex page. Rejected for now.
3. **Precompute every position at import.** Instant at view time but needs a new table and re-import of the games and
   cannot cover positions inside explored lines. Rejected.

The owner delegated the build choice ("I think people would like A" was about the layout only); approach 1 is the
assistant's call.

## Decided design

### Server

`POST /api/analysis` body `{ "fen": str, "depth": int = 16, "lines": int = 3 }`:

- Validate `fen` with python-chess (illegal or malformed: 422); clamp `depth` to 1..20 and `lines` to 1..5 (or reject
  out-of-range with 422; builder's choice, tested); an overlong `fen` string is rejected (`max_length`).
- A game-over position (mate or stalemate) returns `{ "game_over": true, "result": "checkmate" | "stalemate" |
  "draw" }` with no engine call; the page shows a clear note instead of lines.
- Otherwise run the shared engine with `multipv = lines` and a **time cap** (a few seconds; add an optional time
  argument to `EngineService.analyse`) so one request cannot hold the lock long. Response:
  `{ "version": str, "depth": int, "lines": [ { "score": { "cp": int | null, "mate": int | null }, "moves": [ { "san":
  str, "uci": str, "fen": str, "capture": bool, "check": bool } ] } ] }`, scores in **White's perspective**
  (`mate` is moves-to-mate, the UCI/python-chess convention carried by `Analysis.mate`, signed: positive = White
  mates; the page prints `M<n>` and `-M<n>`), `moves` being the principal variation
  (capped at a sensible length such as 12 plies); `fen` is the position AFTER that move, so the page can show each
  step without chess logic.
- **Search limit.** Use both limits together (`chess.engine.Limit(depth=<requested>, time=<cap>)`, whichever is reached
  first); `Engine.analyse` and `EngineService.analyse` gain the optional time argument with tests. The response
  `depth` is the depth **actually reached** (shown in the header), the cache is keyed by the **requested**
  `(normalised fen, depth, lines)` and stores the reached depth with the result, bounded in-memory LRU (builder
  chooses size, for example 256).
- **Engine contention.** The shared engine has one lock and no cancellation, so the endpoint must bound how long
  analysis can delay a guess or chat: at most **one** analysis request waits for the engine at a time (a newer
  request replaces an older waiting one, which returns quickly as "superseded"/busy and is simply dropped by the
  page), an analysis waits for the engine for at most about two seconds before answering 503 "engine busy", and an
  analysis must not take the engine ahead of a waiting guess or chat (guess/chat get priority when both wait). The
  guarantee: a guess or chat waits for at most one running analysis (one time cap), never a queue of them. The page
  treats "busy"/"superseded" as retry-quietly while the position is still selected. The mechanism is the builder's
  choice; the guarantee is tested with a fake slow engine.
- Errors: engine failure gives 503 with a message, other exceptions are logged and surface as 500, same as guess.

### Evaluation bar (page)

- Left of the board, same height as the board, bordered with theme tokens; White's share fills from the bottom
  (White at the bottom) or the top (board flipped), computed from the score with a smooth non-linear mapping (a pawn
  advantage should move the bar visibly; large advantages saturate; mate fills fully), clamped so a tiny sliver is
  always visible. The score text is printed on the bar on the side of the leading colour.
- Value source: **stored** evaluation for the position before the selected move (convert `cp_best` from the mover's
  perspective to White's; a stored mate cap shows as `Mate` without a number) until the **live** value arrives,
  then the live one (top line). While exploring, only live values apply (before they arrive, keep the previous
  value, shown dimmed). If the live and stored values disagree a little, the bar eases to the live one.
- `role="img"` with an `aria-label` such as "Evaluation: White is ahead by 0.4 pawns"; neutral text when hidden.

### Analysis tab and lines (page)

- The right column gets two tabs, **Coach** (today's caption content) and **Analysis**. The selection is remembered
  (`settings`). The default tab is **Coach** and the analysis toggle defaults to on, so the bar shows immediately and
  the Analysis tab is one click away.
- Each line: a score badge (white badge for White ahead, dark for Black ahead, as in the reference) and its moves as
  SAN with move numbers, truncated with an ellipsis; each line is a button named like "Line 1, plus 0.40, 11. b3 Re8 ...".
  The header shows "Stockfish <version> . depth <n>".
- States: thinking (spinner-free text, skeleton rows), loaded, error (503 message with retry), game over note.
- Requests are made only when the Analysis tab is open **or** the bar needs a live value (builder's call; at minimum
  one request per newly selected position, debounced so holding an arrow key does not queue a request per step, and
  stale responses are discarded by identity/token like the explain and guess races).

### Exploring mode (page)

- State: the real game position (selected move) plus `exploring: { path, step }` where `path` is the list of moves
  (each with its FEN and capture/check flags, from the server) walked since leaving the game position, and `step` the
  current index in it. Entering: click a line (or press Enter on it): the path becomes that line's moves.
  **Clicking a line while already exploring** (the panel then shows lines for the explored position) keeps the
  path up to the current step and appends the clicked line's moves, so exploration continues from where the user is
  and Left still walks all the way back to the game position. The board shows the
  position after the clicked line's first move, highlights the last move, shows no engine arrows, and plays the
  base move sound (capture/check/move) per step from the server's flags. The bar and lines update for the
  explored position (a new analysis request per step, cached).
- Stepping: Left/Right (and the path's move buttons) move within the path; at the start of the path one more Left
  returns to the game position; at the end of the path Right does nothing. A banner states "Exploring a line" with
  the line text and a **Back to the game (Esc)** button.
- Leaving: Esc, the Back button, selecting another game, or navigating the game with `j`/`k`/first/last/the strip
  restores the real game position and exits exploring; nothing explored persists. Esc ordering becomes: modal >
  chat drawer > active guess > exploring.
- While exploring, chat and "Explain this move" still refer to the **real game move**, not the explored position;
  the UI keeps that clear (the banner is visible).

### Guess-first integration

At a guessable, not-yet-answered key moment (the neutral pre-guess view) and during an active guess, the bar and
the Analysis tab show a neutral "Hidden until you guess" state: no values, no lines, **no analysis request is
made**, exploring cannot be entered, and the neutral aria labels are used. After the reveal or "Show the answer"
they behave normally. All existing neutrality rules from the immersive UI spec still hold.

### Toggle and keys

- Top-bar control "Analysis" on/off (`aria-pressed`), key `a` (ignored while typing); when off, the bar and tab are
  hidden, no analysis requests are made, and exploring mode exits. Remembered in settings (key `analysis`).
- Shortcut list (`?` dialog) and README updated.

## My calls (the owner did not decide these; change them freely)

- Three lines, depth 16, a few seconds' time cap, a PV capped around 12 plies; analysis on by default; default tab
  Coach; key `a`; scores shown in pawns with two decimals (bar one decimal).
- Hidden-until-guess behaviour as above (the bar's value would also hint at the answer's quality).
- Chat and Explain stay about the real game move while exploring; `j`/`k`/strip navigation exits exploring.
- Per-step sounds while exploring: the base move/capture/check sound only (never best/blunder cues).
- Clicking a line while exploring extends the path from the current step (Chess.com behaviour); mate distance is
  in moves; the search uses depth and time limits together and shows the depth actually reached.
- Engine contention policy: one waiting analysis at most, newest wins, analysis defers to guess/chat, about a
  two-second wait before "busy".
- No opening name and no visible move list in this version.

## Left to the builder

- Exact styling (bar width, badge look, tab look) within the theme tokens; the bar's fill mapping curve.
- Cache sizes and exact caps; whether out-of-range `depth`/`lines` are clamped or rejected (be consistent and test it).
- Debounce interval and the policy for when requests are made (tab open versus bar-driven).
- Test strategy: server tests with a fake engine (as `test_guess.py` does); node tests for the pure helpers (score
  formatting including mate and Black-ahead, bar fill, line text truncation, exploring-state transitions); a manual
  browser checklist.

## Success

- With analysis on, stepping through a game updates the bar instantly from stored values and the lines within a
  couple of seconds; clicking a line steps the board through the engine's variation, the bar and lines following,
  and Esc returns to exactly where the user was.
- At a guessable unanswered key moment and during a guess nothing about the engine's evaluation or lines is visible
  and no analysis request is sent (verified by test or network inspection).
- A guess or chat request waits for at most one running analysis (one time cap), never a queue of them, verified with
  a fake slow engine; the 503/busy paths show a clear message or retry quietly.
- Toggling analysis off removes the bar and tab and stops requests; the choice survives a reload.
- Scores are correct in White's perspective in both colours' turns and for mates, covered by tests.
