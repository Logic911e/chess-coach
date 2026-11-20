# Immersive review UI: design

Status: implemented 2026-11-20 (see docs/superpowers/plans/2026-11-20-immersive-ui.md).

## Intent and why

Chess Coach already analyses a player's own games with Stockfish, finds their mistakes ("key
moments"), and has a small local model explain them in plain language. The current page is a flat
dashboard (game list, board, text panel). The owner (an undergraduate building a portfolio piece)
wants it to feel **immersive**: somewhere you are happy to sit and study one position for a long
time, not a report you skim.

What the owner said immersive means, in their words: visually aesthetic, pleasing sounds, and
something a user can look at for a long time without eye strain. They named certain Chess.com
themes as a reference point for the feeling (not for copying). They also said they do not want
many things on screen when the user is focusing on one position.

A chatbot is the original goal of the project; a chat with no good interface around it is
"useless" in the owner's words. So the coach conversation is part of this screen, not a separate
page.

## Goals

- A **theatre layout**: the board is the stage; everything else is quiet and optional.
- **Three themes**, switchable at any time and remembered: Walnut (warm lamplight, wood-grain
  board, serif coach voice), Slate (cool dark, muted green board) and Paper (light, warm cream,
  low glare). All built for long sessions: no pure white or pure black, no glare.
- **Two sound palettes**, Felt (default) and Wood, plus off, with a volume control. Events: move,
  capture, check, best move, blunder, key-moment reveal. Quiet by default.
- **Keyboard first**: step through moves, jump between key moments, open chat, guess, without the
  mouse.
- **Guess the better move** at a key moment: the user plays a move on the board, the server checks
  it is legal and has the engine score it, then the coach reveals the engine's move and
  explanation.
- **Chat docked to the position**: a drawer that opens on demand and answers questions about the
  selected position from the engine facts, with the existing checks on moves and piece squares.
- **Study mode**: one switch that turns off motion and sound; also honours `prefers-reduced-motion`.

## Non-goals (this version)

- Accounts, logins, multiple users, hosting, payments.
- A hosted or larger model. The local Ollama model stays.
- "Your patterns" across games and a retry-your-blunders queue (good ideas, later).
- Mobile-first design. It must not break on a narrow window, but the desktop experience leads.
- Importing games from the page, or analysing a position the user types in.
- Copying Chess.com or Lichess assets, branding or layout. The look is original.

## Anti-goals (a failure even if it technically works)

- Streaks, guilt notifications, fake urgency or rewards that do not track real improvement.
- Sound that plays by itself, or any effect the user cannot switch off.
- Atmosphere that lowers legibility: dim overlays on the board, low-contrast text, animation that
  slows down stepping through moves.
- A screen that needs scrolling to reach the board controls, or a cluttered screen while the user
  is looking at a position.
- Making explanations sound more trustworthy than they are (see Constraints).

## Constraints

- **Existing system stays.** Python 3.11+, FastAPI (`src/chess_coach/api.py`), Postgres, python-chess,
  Stockfish as an external process, local Ollama model. All chess logic and all checks live on the
  server; the page does no chess logic (no legality or engine work in JavaScript).
- **Plain HTML, CSS and JavaScript** served from `src/chess_coach/web/`, no build step, no
  framework. Libraries only if clearly worth it and licence-checked.
- **Licences.** Pieces are the Chessnut set (Apache 2.0, credited in `web/pieces/LICENSE.txt`).
  Anything new must be permissive or the owner decides. Sounds are generated in the browser with the
  Web Audio API, so there are no audio files to license. The project is non-commercial.
- **Honesty about the model.** Explanations come from a small local model and are checked only for
  illegal moves and wrong piece squares. They can still be wrong or vague, and the page keeps a short
  note saying so near every generated text, chat included.
- **Accessibility:** respect `prefers-reduced-motion`; keep text contrast at WCAG AA or better in all
  three themes; keyboard-reachable controls with visible focus; a screen-reader-readable move list
  and a live region for the caption.
- **Performance:** no heavy WebGL or blur on the board; the local model is slow (10 to 20 seconds),
  so show progress and never block stepping through moves while it works.
- **Browser:** current Chrome, Safari and Firefox. Audio is blocked until the first user gesture, so
  sound starts only after a click or key press.

## Approaches considered

1. **Evolve the current vanilla page (chosen).** Themes as CSS variables, sound from Web Audio,
   board animation by hand. No build tools, explainable in an interview, cheap to change.
2. **Rebuild in React with a build step.** Better for a large team or bigger UI. Rejected for now:
   rewrite of working code and tooling for no visible gain at this size. The clean API boundary keeps
   a later move to React a front-end-only change.
3. **Use a board library (chessground).** Polished animation and drag and drop. Rejected for now:
   it is GPL-3.0 as far as the owner's assistant understands (to be verified), which would force the
   shipped front end to be GPL-compatible and would be a problem if the project ever became
   commercial. Revisit only if hand-written piece animation is too fiddly.

The owner chose approach 1 after asking which was best if the project became commercial. The main
commercial blockers are not the framework: they are licences (python-chess and Stockfish are GPL),
the local-model design, and missing accounts and hosting. Those are out of scope here.

## Decided design

### Layout (theatre)

- Full-window page with a thin top bar: product name, game title and move counter on the left;
  theme, sound and study-mode controls on the right. A slim "Games" entry opens the game list as
  an overlay, not a permanent column.
- Centre: the board, as large as fits without scrolling, with the position before the selected
  move, two arrows (move played in the label colour, engine's move in green) and last-move
  highlight, as today.
- A **caption card** over the lower edge of the board area holds the move name and label, one
  line of "what happened" (expected points lost, best move) and, for a key moment, the coach's
  explanation. Buttons on it: Guess first, Show engine move, Ask the coach.
- A thin **move strip** (cost bars, as today) under the board for jumping about, which collapses
  to nothing in focus moments.
- A **chat drawer** that slides up from the bottom right on demand. Closed by default.
- Nothing else is on screen while the user studies a position.

### Themes

Three themes defined as CSS custom properties on the document root and selected by a
`data-theme` attribute: `walnut`, `slate`, `paper`. The mockups in
`docs/superpowers/specs/2026-11-20-immersive-ui-mockups/mood.html` (and `layout.html` for the theatre layout; open them via the running app, which serves the pieces) show the intended palette, board
colours and serif/sans split; the builder may adjust exact values for contrast. The wood-grain
texture applies to Walnut only. Choice is saved in `localStorage` (wrapped in try/catch; the page
must work without it). Default: Walnut (builder's call is allowed to change this if contrast
fails).

### Sound

Synthesised with the Web Audio API; recipes for Felt and Wood are in
`docs/superpowers/specs/2026-11-20-immersive-ui-mockups/sound.html` (move, capture, check, best move,
blunder, key moment). Felt is the default palette. A mute toggle and a volume slider; saved in
`localStorage`. Study mode mutes. The audio context is created on the first user gesture.
The Chime palette was rejected by the owner.

### Interaction

- Keyboard: Left/Right step; `J`/`K` next/previous key moment; `G` guess; `/` focus the chat input
  and open the drawer; `Esc` closes the drawer or a guess; `M` mute; `?` shows the shortcut list.
- Motion: pieces slide between positions; arrows draw in. All of it off in study mode and under
  `prefers-reduced-motion`.

### Guess the better move

At a key moment where the user was the mover, "Guess first" hides the engine arrow and lets the user
click a piece then a square. The page sends the move to the server (UCI). The server checks
legality with python-chess, has Stockfish score the resulting position at the same depth used on
import, and returns whether it matched the best move, its label and expected points lost, and the
best move. The page then reveals the caption and plays the right sound. An illegal move is
rejected with a gentle message and does not count as an attempt.

### Chat

A drawer with a message list and one input, scoped to the selected position. The server builds the
facts record for that move (key moments already have one; for other moves it can be built from the
stored evaluation), renders it as plain statements (`narrative.py`), adds the user's question and
a short recent history, and asks the local model. The answer goes through the existing
`check_claims` guardrail (retry then flag) before it is shown. The drawer carries the same short
note about limits as explanations.

### API additions

- `POST /api/moves/{id}/guess` with `{uci}` returns legality, whether it matched the engine's move
  exactly, label, expected points lost, and the best move in SAN.
- `POST /api/moves/{id}/chat` with `{question, history}` returns `{body, flagged}`.
- `GET /api/games/{id}` moves gain `capture` and `check` booleans (for sounds), and the games
  list gains nothing new. A small `GET /api/players` returns player names with game counts, used to
  work out who "me" is.
- Existing endpoints stay. The page stores no chess state except the selected game and move.

## My calls (the owner did not decide these; change them freely)

These settle the questions an independent reviewer raised on the first draft.

- **Engine in the API.** One long-lived Stockfish process, started on first use, shared by guess
  and chat and serialised behind a lock (one analysis at a time). Depth: the stored depth of that
  move's evaluation. The tests inject a fake engine, as the analyser tests already do.
- **Chat on moves without a stored engine line.** Evaluations store only the best move and scores,
  not the line. For chat the server asks the engine for the line on demand and uses it to build the
  facts and the guardrail's truth boards. No schema change and no re-import.
- **Moves the user names in a chat question** (for example "what if I play Nf3?"): if legal in the
  position, they are added to the guardrail's truth boards, so a correct answer about them is not
  flagged. Illegal ones are not added, so an answer treating them as playable is flagged.
- **Guesses are not stored.** One attempt per key moment per visit, then reveal. An illegal move is
  rejected without using the attempt. Storing guesses is the first step of the later "retry your
  blunders" feature and needs a migration, so it waits.
- **"Matched"** means exactly the engine's best move. Any other legal move gets its label and
  expected points lost, so an equally good alternative shows as "excellent" or "good", not wrong.
- **Reveal text.** After a guess the caption shows one line ("Your guess: Nf3, a good move, lost
  0.01. Engine: b3") followed by the existing explanation of the move actually played, generated on
  demand with a progress indicator if it is not cached. No third prompt in this version.
- **Who "me" is.** The page asks the server for player names with game counts. If one name appears
  in a clear majority of games, that is "me". If it is ambiguous, the page asks once ("Which
  player are you?") with a list, and remembers the answer by name in `localStorage`. Until a name is
  chosen, guess-first is hidden. No username is hard-coded in the repository.
- **Sounds for move properties.** The API provides `capture` and `check` flags. When stepping onto
  a move, the page plays the move, capture or check sound, then a best-move or blunder sound on
  top if the label calls for it. Blunder sound only for mistakes and blunders.

- Default theme Walnut; default sound Felt.
- "Me" in a game (for "key moment where the user was the mover") is the player name that appears
  in most imported games, overridable by a setting saved in `localStorage`.
- Guess-first applies to key moments only, and only where the user was the mover.
- Chat history sent to the model is capped to the last few turns.
- The Games list is an overlay, not a permanent rail.
- Shortcut keys listed above.

## Left to the builder

- Exact colours, spacing and type sizes, within the rules above (contrast AA, no pure white/black).
- Animation timings and easing; arrow draw-in implementation.
- Piece movement technique (CSS transforms on the existing grid versus an overlay layer).
- How the caption card and chat drawer are laid out at narrow widths.
- Prompt wording for chat and how many history turns to send.
- Test strategy for the new endpoints (the existing suite uses a throwaway Postgres and fake
  engine/model clients) and a manual checklist for the front end.

## Success

- A user can review a whole game and ask a question about a position using only the keyboard,
  without the page scrolling.
- Switching themes and sound palettes works and survives a reload; sound never plays before a user
  gesture; study mode removes all motion and sound.
- A guessed move is judged by the engine and the reveal is correct for the best move, a good move,
  a mistake and an illegal move.
- Chat answers about a position are checked by the same guardrail as explanations and are flagged
  when the check fails.
- The page keeps the visible note that generated text can still be wrong.
