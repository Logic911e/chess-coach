# Immersive Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the review page into a themed, sound-enabled, keyboard-first "theatre" with guess-the-better-move and a position-scoped chat, backed by new API endpoints.

**Architecture:** The FastAPI app gains a shared, lock-guarded Stockfish service and three new capabilities (guess, chat, players) plus two extra move flags. The page is rewritten as small ES modules (no build step) over CSS-variable themes; all chess logic stays on the server. Pure front-end logic lives in modules that `node --test` can run.

**Tech Stack:** Python 3.11+, FastAPI, psycopg, python-chess, pytest; plain HTML/CSS/ES modules, Web Audio, Node (only for `node --test`).

**Spec:** `docs/superpowers/specs/2026-11-20-immersive-ui-design.md` (mockups in `docs/superpowers/specs/2026-11-20-immersive-ui-mockups/`; run the app on :8000 so their piece images load).

## Global Constraints

- Plain HTML, CSS and JavaScript in `src/chess_coach/web/`; no build step, no framework, no new JS library.
- The page does no chess logic (no legality, no engine work in JavaScript).
- Python 3.11+; ruff line length 100; every task ends with `pytest -q` and `ruff check src tests` green.
- Text from the server is inserted with `textContent`, never `innerHTML`.
- Themes: `data-theme` on the root, values `walnut` (default), `slate`, `paper`. No pure white or pure black; body text contrast >= 4.5:1 in all three.
- Sound: Web Audio only (no audio files); palettes `felt` (default) and `wood`, plus off; audio context created on the first user gesture; study mode mutes. Chime is rejected.
- Honesty note ("checked for legal moves and piece squares only, so it can still contain mistakes") stays visible next to every generated text, chat included.
- Every effect has an off switch; study mode and `prefers-reduced-motion` remove all motion and sound.
- `localStorage` access is wrapped in try/catch and the page works without it. No username is hard-coded in the repository.
- Pieces: the Chessnut set already in `web/pieces/` (Apache 2.0). New assets must be permissive.
- Conventional commits; end each commit message with the two attribution lines from the session's commit reminder.

## Review Focus

1. A guess that ends the game (checkmate or stalemate): scoring must not call the engine on a finished game (checkmate scores as a win, stalemate as 0). Pinned in Task 3.
2. A guess that is a pawn promotion: the page must send the promotion letter, and a promotion square without one is rejected as not legal. Pinned in Task 3.
3. `localStorage` throwing (private window, blocked storage): the page still loads, themes and sound still work for the session. Pinned in Task 5.
4. A chat question that is empty, huge, or names a nonsense move: it must return a clear error or a normal answer, never a 500 and never a false "flagged". Pinned in Task 4.
5. The engine or the model failing mid-request, and a guess and a chat arriving together: a 503 with a message, the lock released, no stuck process. Pinned in Tasks 1, 3 and 4.
6. A game with no key moments, the first and last move, and a flipped board: stepping, arrows and the strip must not break. Pinned in Task 6.

---

## File Structure

- `src/chess_coach/engine_service.py` (new): shared Stockfish, lazy start, one analysis at a time.
- `src/chess_coach/api.py` (modify): wire the service; flags; `/api/players`; guess and chat endpoints.
- `src/chess_coach/guess.py` (new): `score_guess` (pure given an engine).
- `src/chess_coach/chat.py` (new): facts for any move, moves named in a question, `answer_question`.
- `src/chess_coach/explainer.py` (modify): extract the retry loop so chat reuses it.
- `src/chess_coach/web/`: `index.html`, `css/themes.css`, `css/app.css`, `js/{main,api,board,settings,sound,keys,guess,chat,me}.js`; delete `app.js` and `style.css`.
- `tests/web/*.test.mjs` (new): `node --test` for pure front-end logic.

---

### Task 1: Shared engine service

**Files:** Create `src/chess_coach/engine_service.py`, `tests/test_engine_service.py`; Modify `src/chess_coach/api.py` (`create_app` takes `engine_service`; closes it on shutdown).

**Interfaces:**
- Produces: `class EngineService` with `__init__(self, factory: Callable[[], ContextManager[EngineLike]] = Engine)`, `analyse(self, board: chess.Board, depth: int, multipv: int = 1) -> list[Analysis]` (lazy start on first call, serialised by a `threading.Lock`), and `close(self) -> None` (idempotent). `create_app(connect=..., client_factory=..., engine_service: EngineService | None = None)`; endpoints call `app.state.engine`.

- [ ] **Step 1: Write failing tests** in `tests/test_engine_service.py`: `test_starts_lazily_and_only_once` (factory call count is 0 before the first `analyse`, 1 after two calls); `test_calls_are_serialised` (two threads; a fake engine records overlapping entry; assert never more than one inside); `test_close_is_idempotent_and_releases_engine` (fake `__exit__` called once after two `close()`); `test_error_in_engine_releases_lock` (first call raises, second call still runs).
- [ ] **Step 2: Run** `pytest tests/test_engine_service.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `EngineService`** in `engine_service.py`; enter the factory's context manager once and keep it with `contextlib.ExitStack`. In `create_app`, default to `EngineService()` and close it in a FastAPI lifespan handler.
- [ ] **Step 4: Run** the new tests plus `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: shared lock-guarded Stockfish service for the API`.

### Task 2: Move flags and players endpoint

**Files:** Modify `src/chess_coach/api.py`; Test `tests/test_api.py`.

**Interfaces:**
- Produces: each move in `GET /api/games/{id}` gains `capture: bool` and `check: bool` (computed with python-chess from `fen_before` and `uci`; check true when the move gives check or mate). New `GET /api/players` returns `{"players": [{"name": str, "games": int}, ...], "suggested": str | None}` sorted by `games` descending; `suggested` is the name appearing in more than 50% of games, else `None`. Helper `suggest_player(counts: dict[str, int], total_games: int) -> str | None`.

- [ ] **Step 1: Write failing tests**: `test_move_flags` (after `1. e4 e5 2. Qh5`, `Qh5` has `check False`, `capture False`; use a PGN with `Bxf7+` to assert `capture True` and `check True`); `test_suggest_player_majority_and_ties` (3 of 5 games -> the name; 2 of 4 -> `None`; zero games -> `None`); `test_players_endpoint_counts_each_game_once` (a game where the same name is both colours counts once).
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement** the flags in `get_game`, `suggest_player`, and the endpoint (one SQL query counting distinct games per name across `white` and `black`).
- [ ] **Step 4: Run** `pytest -q`; pass. **Step 5: Commit** `feat: capture/check flags on moves and a players endpoint`.

### Task 3: Guess endpoint

**Files:** Create `src/chess_coach/guess.py`, `tests/test_guess.py`; Modify `api.py`; extend `tests/test_api.py`.

**Interfaces:**
- Consumes: `EngineService.analyse`; `features.expected_points_lost(cp_best, cp_played)` and `features.classify(loss)`; `features.MATE_CP`.
- Produces: `score_guess(fen: str, uci: str, best_uci: str, cp_best: int, depth: int, engine: EngineLike) -> GuessResult` where `GuessResult` is a dataclass `{legal: bool, matched: bool, classification: str | None, expected_points_lost: float | None, san: str | None}`. `POST /api/moves/{id}/guess` body `{"uci": str}` returns that plus `best_san: str`; 404 for an unknown move; 503 with a message if the engine fails.

- [ ] **Step 1: Write failing tests** in `tests/test_guess.py` with a fake engine (reuse the `Swingy`-style fake): `test_exact_best_move_matches_without_engine_call` (`matched True`, label from `cp_best` vs itself = `best`, engine call count 0); `test_alternative_move_is_scored_by_engine` (`matched False`, label and loss from `min(cp_best, -engine_cp)`); `test_illegal_move_is_not_scored` (`legal False`, engine not called); `test_promotion_without_letter_is_illegal` (position with a pawn on e7, `e7e8` -> `legal False`, `e7e8q` -> legal); `test_checkmating_guess_scores_as_win_without_engine` (`Ra8#` -> loss 0, label `best`-or-`excellent` by value, engine not called); `test_stalemating_guess_scores_zero` (cp 0, engine not called).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement `score_guess`**, mirroring the logic in `evaluation.prepare`: terminal positions score `MATE_CP`/0; otherwise `min(cp_best, -engine.analyse(after, depth)[0].cp_capped)`. In the endpoint use the move's stored `engine_depth` and `cp_best`.
- [ ] **Step 4: API tests**: `test_guess_endpoint_scores_and_404s` and `test_guess_endpoint_503_on_engine_error` (fake engine raises; response 503 and a second request still succeeds).
- [ ] **Step 5: Run** `pytest -q`; pass. **Step 6: Commit** `feat: guess endpoint scoring a user's move with the engine`.

### Task 4: Chat endpoint

**Files:** Create `src/chess_coach/chat.py`, `tests/test_chat.py`; Modify `explainer.py`, `api.py`.

**Interfaces:**
- Produces in `explainer.py`: `run_checked(messages: list[Message], client: ChatClient, boards: list[chess.Board], max_retries: int = 2) -> Explanation`, the retry loop currently inside `explain` (which then calls it; behaviour and its tests unchanged).
- Produces in `chat.py`: `facts_for_move(fen: str, played_uci: str, best_uci: str, cp_best: int, cp_played: int, depth: int, engine: EngineLike) -> tuple[dict, list[str]]` (facts via `features.build_facts` from the stored best move and scores, with the engine line fetched on demand at `depth`; returns facts and the line in UCI); `named_moves(fen: str, text: str) -> list[str]` (legal SAN or UCI moves mentioned in `text`, as UCI); `answer_question(facts: dict, line: list[str], fen: str, question: str, history: list[dict], client: ChatClient) -> Explanation`. `POST /api/moves/{id}/chat` body `{"question": str, "history": [{"role": "user"|"assistant", "content": str}]}` returns `{"body": str, "flagged": bool}`.

- [ ] **Step 1: Write failing tests** in `tests/test_chat.py`: `test_named_moves_keeps_only_legal` (`"what if I play Nf3 or Qz9?"` from the start position -> `["g1f3"]`); `test_answer_not_flagged_for_user_named_legal_move` (fake client replies "Nf3 develops the knight"; not flagged); `test_answer_flagged_when_it_names_a_move_not_legal_anywhere`; `test_history_is_capped_to_last_6_messages`; `test_empty_or_oversized_question_rejected_with_422` (blank, and longer than 1000 characters); `test_chat_503_when_model_down`. Add `test_run_checked_retries_then_flags` in `tests/test_explainer.py` if not already covered by the existing explain tests.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Refactor** `explain` to build messages then call `run_checked`; run `pytest tests/test_explainer.py` to prove no behaviour change.
- [ ] **Step 4: Implement** `chat.py` and the endpoint. Prompt: the statements prompt from `narrative.render_facts`, then the capped history, then the question; system rule: answer only from the statements, say so when the answer is not in them. Truth boards = `truth_boards(...)` plus a board after each move from `named_moves`.
- [ ] **Step 5: Run** `pytest -q`; pass. **Step 6: Commit** `feat: position-scoped chat with the claims guardrail`.

### Task 5: Theme system, settings and page shell

**Files:** Create `web/css/themes.css`, `web/css/app.css`, `web/js/settings.js`, `tests/web/settings.test.mjs`, `tests/web/contrast.test.mjs`; Modify `web/index.html`; Delete `web/app.js`, `web/style.css` after Task 6 replaces them (keep both working until then).

**Interfaces:**
- Produces: `settings.js` exports `createSettings(storage: Storage | undefined): { get(key, fallback), set(key, value) }` that never throws (falls back to an in-memory map); keys `theme`, `soundPalette` (`felt|wood|off`), `volume` (0..1), `studyMode`, `me`. `themes.css` defines `:root[data-theme="walnut|slate|paper"]` with tokens `--bg`, `--panel`, `--ink`, `--muted`, `--accent`, `--bad`, `--board-light`, `--board-dark`, plus `--grain` on walnut only.

- [ ] **Step 1: Write failing tests**: `settings.test.mjs` — `test_works_when_storage_throws` (storage whose `getItem`/`setItem` throw: `get` returns the fallback, `set` then `get` returns the new value), `test_roundtrip_with_storage`, `test_rejects_unknown_theme_value_falls_back_to_walnut`; `contrast.test.mjs` — parse `--ink` and `--bg` (and `--ink` on `--panel`) for each theme from `themes.css` and assert WCAG ratio >= 4.5, and that no token equals `#fff`, `#ffffff`, `#000` or `#000000`.
- [ ] **Step 2: Run** `node --test tests/web`; expect FAIL.
- [ ] **Step 3: Implement** `settings.js` and `themes.css` (palettes from the mood mockup; adjust values until the contrast test passes). Add a theme switcher (three dots) and a study-mode toggle to the top bar in `index.html`, applying `data-theme` from settings at load.
- [ ] **Step 4: Run** `node --test tests/web` and `pytest -q`; pass. **Step 5: Verify in the browser** (see Manual checklist, theme items). **Step 6: Commit** `feat: three themes with safe settings storage`.

### Task 6: Theatre layout and board module

**Files:** Create `web/js/{main,api,board}.js`; Modify `web/index.html`, `web/css/app.css`; Delete `web/app.js`, `web/style.css`; Test `tests/web/board.test.mjs`.

**Interfaces:**
- Produces: `board.js` exports `parseFen(fen: string): (string|null)[][]`, `squareXY(name: string, flipped: boolean): [number, number]`, and `renderBoard(el, fen, { flipped, highlight: string[], arrows: {uci: string, color: string}[], animateFrom?: string })`. `api.js` exports `getGames()`, `getGame(id)`, `getPlayers()`, `explainMove(id, regenerate)`, `guessMove(id, uci)`, `chatMove(id, question, history)`; each throws `Error` with the server's `detail`.

- [ ] **Step 1: Write failing tests** in `board.test.mjs`: `test_parse_fen_start_position` (rank 8 first, `rnbqkbnr`); `test_square_xy_flipped` (`a1` unflipped is `[0.5, 7.5]`, flipped `[7.5, 0.5]`); `test_arrow_of_same_move_is_deduplicated` (played equals best gives one arrow).
- [ ] **Step 2: Run**; expect FAIL. **Step 3: Implement** the modules and the theatre layout: thin top bar; board as large as fits without scrolling; caption card over the board's lower edge (move name, label pill, one line, buttons Guess first / Show engine move / Ask the coach, explanation text with the honesty note); strip under the board; Games as an overlay opened from the top bar; chat drawer markup present but closed. Keep the working behaviour of today's page (explain button, key-moment navigation).
- [ ] **Step 4: Edge cases** — add to `board.test.mjs` `test_game_without_key_moments_still_renders_first_move` using a small stub and confirm the next-key-moment lookup returns `-1` instead of throwing.
- [ ] **Step 5: Run** `node --test tests/web`, `pytest -q`, then verify in the browser at 1515x784 that the board and controls fit without scrolling. **Step 6: Commit** `feat: theatre layout with a caption card and games overlay`.

### Task 7: Sound

**Files:** Create `web/js/sound.js`, `tests/web/sound.test.mjs`; Modify `main.js`, `index.html`.

**Interfaces:**
- Produces: `sound.js` exports `soundsFor(move: {capture: boolean, check: boolean, classification: string}): string[]` (ordered event names from `move`, `capture`, `check`, `best`, `blunder`; base sound is `capture` if captured, else `check` if check, else `move`; adds `best` when the classification is `best`, adds `blunder` when it is `mistake` or `blunder`), and `createPlayer({ settings, audioContextFactory })` with `play(events: string[])`, `unlock()`, and `playKeyMoment()`. Palettes `felt` and `wood` use the recipes in `sound.html`.

- [ ] **Step 1: Write failing tests**: `test_sounds_for_capture_with_check_prefers_capture`; `test_blunder_label_adds_blunder_sound_only_for_mistake_and_blunder`; `test_player_makes_no_audio_before_unlock` (fake context factory not called until `unlock()`); `test_study_mode_and_off_palette_are_silent`; `test_volume_zero_is_silent`.
- [ ] **Step 2: Run**; expect FAIL. **Step 3: Implement** with the Web Audio recipes from the mockup; create the context in `unlock()`, which `main.js` calls on the first pointer or key event. Add a sound control (Felt / Wood / Off and a volume slider) to the top bar; play sounds when stepping onto a move.
- [ ] **Step 4: Run** `node --test tests/web`; pass. **Step 5: Verify** in the browser that nothing plays before a click and that Felt and Wood both play. **Step 6: Commit** `feat: synthesised Felt and Wood sound palettes`.

### Task 8: Keyboard, motion and study mode

**Files:** Create `web/js/keys.js`, `tests/web/keys.test.mjs`; Modify `board.js`, `main.js`, `app.css`.

**Interfaces:**
- Produces: `keys.js` exports `createKeyHandler(actions: {step(d), nextKey(), prevKey(), guess(), chat(), close(), mute(), help()}): (event: {key: string, target: {tagName: string}, metaKey?: boolean, ctrlKey?: boolean}) => boolean` returning whether it handled the key. Map: `ArrowLeft/Right` step, `j`/`k` next/previous key moment, `g` guess, `/` chat, `Escape` close, `m` mute, `?` help.

- [ ] **Step 1: Write failing tests**: `test_shortcuts_map_to_actions`; `test_ignores_keys_typed_into_inputs` (target `INPUT`/`TEXTAREA`, except `Escape`); `test_ignores_modified_keys` (Cmd/Ctrl+j is not handled).
- [ ] **Step 2: Run**; expect FAIL. **Step 3: Implement** the handler, a `?` overlay listing shortcuts, piece sliding between positions and arrows drawing in (CSS transitions), all gated by a single `motionAllowed()` that is false in study mode or when `prefers-reduced-motion: reduce` matches. Study mode also mutes sound.
- [ ] **Step 4: Run** `node --test tests/web`; pass. **Step 5: Verify** by reviewing a whole game with the keyboard only, and that study mode stops motion and sound. **Step 6: Commit** `feat: keyboard shortcuts, motion and study mode`.

### Task 9: Guess-first UI

**Files:** Create `web/js/guess.js`, `tests/web/guess.test.mjs`; Modify `main.js`, `board.js`, `app.css`.

**Interfaces:**
- Consumes: `api.guessMove`, `board.renderBoard`, `settings.get('me')`.
- Produces: `guess.js` exports `canGuess(move, me, game): boolean` (key moment, and the mover's player name equals `me`) and `createGuessFlow({ api, ui })` with `begin(move)`, `pick(square)`, which sends UCI (adding `q` when a pawn reaches the last rank) after two picks, and `reveal(result)`. The attempt is spent only when the server reports `legal: true`.

- [ ] **Step 1: Write failing tests**: `test_can_guess_only_own_key_moments`; `test_illegal_guess_does_not_spend_the_attempt` (fake api returns `legal: false`, a second pick is accepted); `test_second_legal_guess_is_ignored_after_reveal`; `test_promotion_pick_appends_queen_letter` (pawn from rank 7 to rank 8 sends `e7e8q`); `test_reveal_line_text` (`"Your guess: Nf3, a good move, lost 0.01. Engine: b3"`).
- [ ] **Step 2: Run**; expect FAIL. **Step 3: Implement.** "Guess first" hides the engine arrow, lets the user click a piece then a square (highlight the source), calls the API, then shows the reveal line plus the existing explanation (generated on demand with a progress indicator) and plays the label's sound. Hidden when `canGuess` is false.
- [ ] **Step 4: Run** `node --test tests/web`; pass. **Step 5: Verify** best move, a good alternative, a mistake and an illegal move on a real game. **Step 6: Commit** `feat: guess the better move at key moments`.

### Task 10: Chat drawer and "me"

**Files:** Create `web/js/chat.js`, `web/js/me.js`, `tests/web/chat.test.mjs`, `tests/web/me.test.mjs`; Modify `main.js`, `index.html`, `app.css`.

**Interfaces:**
- Produces: `chat.js` exports `createChat({ api, ui, getMoveId })` with `open()`, `close()`, `send(text)`; it keeps history per move (cleared on move change), trims the question, refuses to send an empty one, and shows the honesty note under each answer plus a warning when `flagged`. `me.js` exports `resolveMe({ stored, players, suggested }): { me: string | null, needsPrompt: boolean }`: the stored name wins if it is among the players; else `suggested`; else `needsPrompt: true`.

- [ ] **Step 1: Write failing tests**: `test_empty_question_is_not_sent`; `test_history_resets_when_the_move_changes`; `test_error_from_api_is_shown_not_thrown` (api rejects with a 503 message; the drawer shows it and stays usable); `test_resolve_me_prefers_stored_name_then_suggested_then_prompt`; `test_resolve_me_ignores_stored_name_not_in_players`.
- [ ] **Step 2: Run**; expect FAIL. **Step 3: Implement** the drawer (slides up bottom right; `/` opens and focuses the input; `Esc` closes) and the one-time "Which player are you?" prompt, saving the choice by name in settings. **Step 4: Run** `node --test tests/web` and `pytest -q`; pass.
- [ ] **Step 5: Verify** chat with a real question on a key moment and on an ordinary move; confirm the answer shows the note and is flagged when the model names an illegal move. **Step 6: Commit** `feat: chat drawer scoped to the position and player selection`.

### Task 11: Accessibility pass and docs

**Files:** Modify `index.html`, `main.js`, `README.md`, `docs/superpowers/specs/2026-11-20-immersive-ui-design.md` (status line only).

- [ ] **Step 1: Add** a visually hidden, screen-reader-readable move list (buttons with the SAN and label), an `aria-live="polite"` region for the caption, visible focus outlines in all themes, and `aria-label`s on the board and controls.
- [ ] **Step 2: Test** `tests/test_api.py::test_index_has_live_region_and_move_list_container` (GET `/` contains `aria-live` and the list container id).
- [ ] **Step 3: Update the README**: the UI section (themes, sound, shortcuts, study mode, guess-first, chat), the new run steps, the `node --test tests/web` command, and an honest "known limits" line (chat is checked for legal moves and piece squares only; sounds and animation need a real browser to evaluate).
- [ ] **Step 4: Run** `pytest -q`, `ruff check src tests`, `node --test tests/web`; all pass. **Step 5: Commit** `docs: accessibility pass and UI documentation`.

## Manual checklist (browser, Chrome, 1515x784 and a 900px-wide window)

- Each of the three themes shows readable text; reload keeps the choice; with storage blocked the page still loads.
- No sound before the first click; Felt and Wood play for move, capture, check, best and blunder; mute and volume work; study mode silences and stills everything.
- A whole game can be reviewed with the keyboard only without scrolling the page; `?` lists the shortcuts.
- Guess first: best move, a good alternative, a blunder and an illegal move all behave as in Task 9; a promotion guess works.
- Chat: a normal question, a question naming a legal move, and an empty question; Ollama stopped shows an error and the drawer remains usable.
- A game with no key moments opens without errors; the board flips; the narrow window stays usable.
