# Analysis Bar and Clickable Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable Chess.com-style evaluation bar and an Analysis tab of three engine lines, where clicking a line walks the board through it and the user can return to the real game.

**Architecture:** A new `POST /api/analysis` endpoint runs the shared Stockfish (bounded by a time cap and a one-waiting-request policy that yields to guess/chat) and returns White-perspective scores plus the position after every move of each line, so the page never does chess logic. The page gets small node-testable modules (`analysis.js` helpers and controller, `explore.js` state machine) and thin DOM adapters wired from `main.js`.

**Tech Stack:** Python 3.11+, FastAPI, python-chess, pytest; plain HTML/CSS/ES modules, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-20-analysis-bar-design.md` (also respect `docs/superpowers/specs/2026-11-20-immersive-ui-design.md`).

## Global Constraints

- Plain HTML, CSS and JavaScript in `src/chess_coach/web/`; no build step, no framework, no new library. Server text is inserted with `textContent`, never `innerHTML`.
- The page does no chess logic: every position it shows comes from the server as a FEN (the page may read move number and side to move from a FEN string only to label lines).
- Python 3.11+; ruff line length 100; every task ends with `PYTHONPATH=src .venv/bin/python -m pytest -q`, `.venv/bin/ruff check src tests` and `node --test tests/web/*.test.mjs` green (the glob form; the bare directory form fails on this Node).
- No schema changes. Existing endpoints and behaviour stay unchanged.
- Scores: White's perspective, positive = White ahead; lines show pawns with two decimals (`+0.20`), the bar one decimal (`+0.4`), mate as `M<n>` / `-M<n>` (n in full moves).
- Search: depth and time limits together (whichever first); the response reports the depth actually reached; requested depth defaults to 16, lines to 3, PV capped at 12 plies; analysis time cap about 3 s; an analysis waits at most about 2 s for the engine.
- Guess neutrality: at a guessable unanswered key moment and during an active guess the bar and Analysis tab are hidden, **no analysis request is made**, exploring cannot start, aria labels are neutral.
- Study mode and `prefers-reduced-motion` remove the bar's transition and all sound; contrast >= 4.5:1 for text in all three themes; settings access stays wrapped in try/catch.
- Conventional commit messages; **do not add any attribution trailers** (no `Co-Authored-By`, no `Claude-Session`, no "Generated with" lines) to commits or PRs.

## Review Focus

1. Score sign: scores and mate distances when **Black** is to move must be flipped to White's perspective (cp and mate), including mate for Black. Pinned in Task 2.
2. Game-over positions (checkmate, stalemate, insufficient material), including reaching one at the end of an explored line: no engine call and a clear note instead of lines. Pinned in Tasks 2 and 5.
3. Rapid stepping (holding an arrow key): requests are debounced, stale responses are discarded, no pile-up of requests or flicker of the bar. Pinned in Task 5.
4. The engine busy, hung or failing: the bar keeps its last value dimmed, the panel offers a retry, and guess/chat are never delayed by more than one analysis cap. Pinned in Tasks 1 and 5.
5. Exploring-state integrity: switching game, flipping, Esc, `j`/`k`, the strip, and the guess flow always return to the exact real-game position; nothing explored persists; Esc ordering modal > chat drawer > guess > exploring. Pinned in Task 6.

## File Structure

- `src/chess_coach/engine.py`, `engine_service.py` (modify): combined limits, priority/contention policy, `version`.
- `src/chess_coach/analysis.py` (new): White-perspective conversion, position analysis, LRU cache.
- `src/chess_coach/api.py` (modify): `POST /api/analysis`.
- `src/chess_coach/web/js/analysis.js` (new): pure score/bar/line helpers and the request controller.
- `src/chess_coach/web/js/explore.js` (new): exploring-path state machine.
- `src/chess_coach/web/js/analysis-ui.js` (new): DOM adapters (bar, lines, banner, tabs).
- `src/chess_coach/web/js/{api,settings,keys,main}.js`, `index.html`, `css/{app,themes}.css` (modify).
- `tests/test_engine_service.py`, `tests/test_analysis.py`, `tests/test_api.py` (modify/new); `tests/web/{analysis,explore,settings,keys,contrast}.test.mjs` (new/modify).

---

### Task 1: Search limits and engine contention policy

**Files:** Modify `src/chess_coach/engine.py`, `src/chess_coach/engine_service.py`; Test `tests/test_engine.py`, `tests/test_engine_service.py`.

**Interfaces:**
- Produces in `engine.py`: `search_limit(depth: int | None, time: float | None) -> chess.engine.Limit` (both set -> both passed, whichever is hit first; neither -> `ValueError`); `Engine.analyse(...)` uses it (the old "time wins over depth" rule is replaced).
- Produces in `engine_service.py`: `class EngineBusy(RuntimeError)`; `EngineService.analyse(board, depth, multipv=1, time=None)` (interactive, blocking, as today plus the optional time); `EngineService.analyse_background(board, depth, multipv=1, time=None, max_wait=2.0) -> list[Analysis]` raising `EngineBusy`; `EngineService.version -> str | None`.
- Policy (mechanism is yours): at most one background analysis waits for the engine; a newer one replaces the waiting one (the replaced call raises `EngineBusy`); a waiting background call yields to any waiting interactive `analyse` call; a background call that cannot get the engine within `max_wait` raises `EngineBusy`. Guarantee: an interactive call waits for at most one running analysis, never a queue.

- [ ] **Step 1: Write failing tests.** `test_search_limit_combines_depth_and_time`, `test_search_limit_requires_one_limit`, `test_background_raises_busy_after_max_wait` (a fake engine held busy longer than `max_wait`), `test_newer_background_replaces_waiting_one`, `test_interactive_goes_before_waiting_background`, `test_interactive_waits_for_at_most_one_analysis` (fake slow engine: one running analysis plus two queued backgrounds plus an interactive; assert the interactive starts after the running one only), `test_engine_failure_in_background_still_restarts_engine`, `test_version_is_none_until_started_then_engine_name`.
- [ ] **Step 2: Run** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_engine_service.py tests/test_engine.py -q`; expect FAIL.
- [ ] **Step 3: Implement** `search_limit`, the optional `time` parameter, `EngineBusy`, `analyse_background` and `version`, keeping the existing restart-after-failure behaviour and the lock released on every path.
- [ ] **Step 4: Run** the full Python suite and ruff; pass. Existing guess/chat callers must be unchanged and still pass.
- [ ] **Step 5: Commit** `feat: depth-and-time search limits and a bounded background analysis path`.

### Task 2: Analysis core and endpoint

**Files:** Create `src/chess_coach/analysis.py`, `tests/test_analysis.py`; Modify `src/chess_coach/api.py`, `tests/test_api.py`.

**Interfaces:**
- Consumes: `EngineService.analyse_background`, `EngineBusy`, `EngineService.version`, `Analysis` (`cp`, `mate`, `pv` as UCI list, `depth`; scores are from the mover's perspective).
- Produces in `analysis.py`: `white_score(a: Analysis, white_to_move: bool) -> dict` returning `{"cp": int | None, "mate": int | None}` in White's perspective; `analyse_fen(fen: str, depth: int, lines: int, run: Callable) -> dict` returning either `{"game_over": True, "result": "checkmate" | "stalemate" | "draw"}` (no engine call) or `{"game_over": False, "version": str | None, "depth": int, "lines": [{"score": {...}, "moves": [{"san","uci","fen","capture","check"}]}]}` (PV capped at 12 plies; `fen` is the position after that move; `depth` the depth actually reached); `class AnalysisCache(max_size=256)` with `get(key)` / `set(key, value)` (LRU).
- `POST /api/analysis` body `{"fen": str (max_length 100), "depth": int = 16, "lines": int = 3}`; depth outside 1..20 or lines outside 1..5 or an illegal/malformed FEN -> 422 (reject, do not clamp); cache key is the requested `(board.fen(), depth, lines)`; `EngineBusy` -> 503 `{"detail": "engine busy"}`; engine failures (the `ENGINE_FAILURES` tuple already in `api.py`) -> 503 with a message; any other exception is logged and surfaces as 500. Time cap constant `ANALYSIS_TIME_CAP = 3.0`.

- [ ] **Step 1: Write failing tests** in `tests/test_analysis.py` with a fake engine: `test_white_score_flips_cp_when_black_to_move`, `test_white_score_flips_mate_sign_when_black_to_move` (Black mating gives a negative White mate), `test_pv_positions_and_flags` (each move's `fen` is the position after it; `capture`/`check` right, including a mating move), `test_pv_is_capped_at_12_plies`, `test_game_over_has_no_engine_call` (checkmate, stalemate, insufficient material), `test_reached_depth_is_reported`, `test_cache_returns_stored_result_without_engine_call`, `test_cache_evicts_least_recently_used`. In `tests/test_api.py`: `test_analysis_endpoint_shape`, `test_analysis_rejects_bad_fen_depth_lines_and_long_fen_with_422`, `test_analysis_busy_returns_503_engine_busy`, `test_analysis_engine_failure_returns_503`, `test_analysis_programming_error_is_500_and_logged`, `test_analysis_second_identical_request_is_a_cache_hit`.
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement** `analysis.py` and the route (the engine call goes through `app.state.engine.analyse_background(board, depth, multipv=lines, time=ANALYSIS_TIME_CAP)`); one cache instance per app.
- [ ] **Step 4: Run** the full Python suite and ruff; pass.
- [ ] **Step 5: Commit** `feat: position analysis endpoint with White-perspective scores and per-move positions`.

### Task 3: Pure front-end helpers and settings

**Files:** Create `src/chess_coach/web/js/analysis.js` (helpers part), `tests/web/analysis.test.mjs`; Modify `js/settings.js`, `tests/web/settings.test.mjs`.

**Interfaces:**
- Produces in `analysis.js` (import cleanly in node; no `window`/`document` at import): `scoreFromStored(cpBest: number, color: "white" | "black") -> { cp: number, mate: null, capped: boolean }` (White perspective; `capped` when `|cp| >= 9000`); `formatScore(score, decimals = 2) -> string` (`"+0.20"`, `"-1.23"`, `"M3"`, `"-M3"`, `"0.00"` for zero; for a capped stored mate, `"Mate"`); `barFill(score) -> number` White's share in `[0.02, 0.98]` (0.5 for equal, monotonic, saturating, mate -> the extreme); `barLabel(score) -> string` (one decimal); `lineText(fen, moves, maxPlies = 8) -> string` (starts from the FEN's move number and side, e.g. `"11. b3 Re8 12. Be3 ..."`, black first gives `"11... Re8 12. Be3"`, ellipsis when truncated); `lineA11yName(index, score, text) -> string` (e.g. `"Line 1, plus 0.40, 11. b3 Re8 ..."`, `"minus"` for negatives, `"mate in 3 for White"` for mates).
- Produces in `settings.js`: keys `analysis` (boolean, default `true`) and `analysisTab` (`"coach"` | `"analysis"`, default `"coach"`), validated like the existing keys (junk falls back to the default).

- [ ] **Step 1: Write failing tests** in `analysis.test.mjs`: `test_score_from_stored_flips_for_black_mover`, `test_stored_mate_cap_is_flagged`, `test_format_score_pawns_signs_and_mate`, `test_bar_fill_is_monotonic_symmetric_and_clamped` (equal = 0.5, `fill(+x) + fill(-x) = 1`, mate at the extremes), `test_bar_label_one_decimal`, `test_line_text_numbers_moves_from_the_fen_and_truncates`, `test_line_text_black_to_move_starts_with_ellipsis_number`, `test_line_a11y_name`; in `settings.test.mjs`: `test_analysis_settings_defaults_and_junk_fallback`.
- [ ] **Step 2: Run** `node --test tests/web/*.test.mjs`; expect FAIL.
- [ ] **Step 3: Implement** the helpers and settings keys.
- [ ] **Step 4: Run** node tests, pytest and ruff; pass. **Step 5: Commit** `feat: score, bar and line helpers for the analysis view`.

### Task 4: Evaluation bar, tabs and toggle (stored values)

**Files:** Create `src/chess_coach/web/js/analysis-ui.js`; Modify `index.html`, `css/app.css`, `css/themes.css`, `js/main.js`, `js/keys.js`, `tests/web/contrast.test.mjs`, `tests/web/keys.test.mjs`, `tests/test_api.py` (markup ids).

**Interfaces:**
- Produces in `analysis-ui.js`: `barView({ score, hidden, off, flipped, live }) -> { fill, label, aria, dim, hidden }` (pure; `hidden` -> neutral aria "Evaluation hidden until you guess" and no label; `off` -> not shown) and DOM adapters `renderBar(el, view)`, `renderTabs(tabsEl, panels, active)`.
- Markup ids: `#evalBar` (left of `#boardWrap`, same height), tab buttons `#tabCoach` / `#tabAnalysis`, panels `#coachPanel` (the existing caption content moves inside it) / `#analysisPanel`, top-bar toggle `#analysisToggle` (`aria-pressed`).
- `keys.js`: action `analysis` on key `a` (toggle), listed in the `?` dialog.
- Theme tokens for the bar (light share, dark share, text) in `themes.css`, covered by the contrast test in all three themes.

- [ ] **Step 1: Write failing tests:** `barView` cases (stored value shows fill and label, hidden is neutral with no label, off, flipped inverts which end fills, `live: false` marks the stored value), `keys.test.mjs` `test_a_toggles_analysis_and_is_ignored_while_typing`, contrast test for the new tokens in each theme (text on the bar's light and dark shares >= 4.5:1), Python `test_index_has_analysis_bar_tabs_and_toggle_ids`.
- [ ] **Step 2: Run;** expect FAIL. **Step 3: Implement** markup, CSS (smooth fill transition removed under study mode and reduced motion, via the existing `data-motion` mechanism), `main.js` wiring: the bar value comes from `scoreFromStored(mv.cp_best, mv.color)` for the position before the selected move, `hidden` from the existing `hiddenNow(mv)`, flips with the board; the toggle and tab choice persist in settings; when analysis is off the bar and tab are hidden.
- [ ] **Step 4: Run** all three suites; pass. **Step 5: Verify in Chrome** (restart uvicorn first): bar fills from White's side, flips with Flip, hides at a guessable unanswered key moment, toggle and `a` work and persist across reload, three themes readable; say what you saw and what you could not check. **Step 6: Commit** `feat: evaluation bar, analysis tab shell and toggle`.

### Task 5: Analysis lines and live requests

**Files:** Modify `js/api.js`, `js/analysis.js` (controller part), `js/analysis-ui.js`, `js/main.js`; Test `tests/web/analysis.test.mjs`.

**Interfaces:**
- Produces in `api.js`: `analysePosition(fen, { depth = 16, lines = 3 } = {}) -> Promise<response>` (POST `/api/analysis`; a 503 with detail `"engine busy"` rejects with an error whose `busy` property is `true`).
- Produces in `analysis.js`: `createAnalysis({ api, ui, delay = 250, retries = 2 })` with `request(fen, { enabled })` (does nothing when `enabled` is false), `invalidate()`, and `peek(fen)`; behaviour: debounce so only the last of a burst of requests is sent, a per-FEN page cache, a token so a stale response is discarded, quiet retry on `busy`, and `ui` callbacks `thinking(fen)`, `loaded(fen, response)`, `gameOver(fen, result)`, `error(fen, message)`, `busyDim()`.
- `analysis-ui.js`: `renderLines(panelEl, state)` for the states thinking / loaded / error (retry button) / game over / hidden, header "Stockfish <version> . depth <n>", each line a button named by `lineA11yName`, score badge (white badge for White ahead, dark for Black ahead).
- `main.js`: on every new selected position request analysis when analysis is on and the position is not hidden; the live top-line score replaces the stored value on the bar (easing); while loading or busy the bar keeps its previous value dimmed.

- [ ] **Step 1: Write failing tests** with a fake `api`/`ui`/timer: `test_burst_of_requests_sends_only_the_last`, `test_stale_response_is_discarded`, `test_cached_fen_makes_no_api_call`, `test_busy_retries_quietly_then_reports_error`, `test_error_state_offers_retry_and_retry_calls_api_again`, `test_disabled_or_hidden_makes_zero_api_calls`, `test_game_over_response_calls_gameOver_not_loaded`, `test_invalidate_drops_in_flight_response`.
- [ ] **Step 2: Run;** expect FAIL. **Step 3: Implement** the controller, `api.js` function and the lines panel; wire into `main.js` (new logic stays in the new modules; `main.js` only calls them).
- [ ] **Step 4: Run** all suites; pass. **Step 5: Verify in Chrome:** lines appear within a couple of seconds, holding an arrow key sends few requests (check the network list), a game-over position shows a note, stopping nothing else; say what you saw. **Step 6: Commit** `feat: engine lines with debounced live analysis`.

### Task 6: Exploring mode

**Files:** Create `js/explore.js`, `tests/web/explore.test.mjs`; Modify `js/analysis-ui.js`, `js/keys.js`, `js/main.js`, `index.html`, `css/app.css`; Test `tests/web/keys.test.mjs`.

**Interfaces:**
- Produces in `explore.js`: `createExplore()` returning `{ begin(lineMoves), extend(lineMoves), step(dir), exit(), active(), position(), path(), atStart() }` where `lineMoves` is the server's `moves` list (`san`, `uci`, `fen`, `capture`, `check`); `position()` returns `{ fen, move, step }` of the current explored position (or `null` when not exploring); `step(-1)` at the first position exits and returns `{ exited: true }`; `step(+1)` at the end of the path is a no-op; `extend` keeps the path up to the current step and appends the new moves (continuing from where the user is).
- Produces in `keys.js`: pure `escapeTarget({ modal, drawer, guess, exploring }) -> "modal" | "drawer" | "guess" | "explore" | null` (that order) used by the Esc action in `main.js`.
- Wiring: clicking a line (or Enter on it) calls `begin` / `extend`; the board shows `position().fen` with the last move highlighted and no engine arrows; each step plays the base capture/check/move sound from the server flags (never best/blunder cues; gated by `motionAllowed()`); the bar and lines follow the explored FEN; a banner (`#exploreBanner`, `role="status"`) shows the explored line and a "Back to the game (Esc)" button; Left/Right step within the path while exploring; `j`/`k`, first/last, strip clicks, game switch, flip-independent state restore, toggling analysis off and starting a guess all `exit()`; chat and Explain stay about the real game move.

- [ ] **Step 1: Write failing tests:** `test_begin_shows_first_move_position`, `test_step_forward_and_back_through_the_path`, `test_step_back_from_the_first_position_exits`, `test_step_forward_at_end_is_noop`, `test_extend_from_middle_truncates_and_appends`, `test_exit_clears_everything`, `test_escape_target_order`, `test_step_keys_walk_the_path_while_exploring` (pure helper deciding what an arrow does).
- [ ] **Step 2: Run;** expect FAIL. **Step 3: Implement** the state machine, the helper and the wiring.
- [ ] **Step 4: Run** all suites; pass. **Step 5: Verify in Chrome:** click a line, walk it with the arrow keys and a click on a move, click another line mid-walk, Esc returns to the exact game position and selected move, `j` and the strip exit, flip works while exploring, the banner shows; say what you saw. **Step 6: Commit** `feat: explore engine lines on the board and return to the game`.

### Task 7: Guess integration, accessibility and docs

**Files:** Modify `js/main.js`, `js/analysis-ui.js`, `index.html` (the `?` dialog, labels), `README.md`, `docs/superpowers/specs/2026-11-20-analysis-bar-design.md` (status line only), `tests/web/analysis.test.mjs`, `tests/test_api.py`.

- [ ] **Step 1: Write failing tests:** `test_hidden_state_is_neutral_in_bar_lines_and_aria` (no label, no lines, no line buttons, neutral text), `test_no_request_while_hidden_even_after_toggle_changes` (controller: zero api calls across hidden -> toggle on/off), `test_exploring_cannot_begin_while_hidden`, Python `test_index_lists_analysis_shortcut_and_banner_ids`.
- [ ] **Step 2: Run;** expect FAIL. **Step 3: Implement:** hide the bar value and the Analysis panel ("Hidden until you guess") whenever `hiddenNow(mv)` or a guess is active and make no request; after the reveal or "Show the answer" show them normally; starting a guess exits exploring; aria: bar `role="img"` with a live-value label, lines named, banner announced politely; the `?` dialog lists `a`, Left/Right-in-line and Esc order.
- [ ] **Step 4: README:** a section for the analysis bar and lines (toggle, `a`, tabs, exploring, scores in pawns, hidden until you guess), the new endpoint and its limits, and honest Known limits: scores are Stockfish at limited depth with a time cap and can differ from a desktop engine; lines appear after a short delay; nothing has been tested with a screen reader; a busy engine can delay lines; opening names and a visible move list are not included. Claim only what was seen or tested.
- [ ] **Step 5: Run** all suites; pass. **Step 6: Verify in Chrome** the guess flow end to end with analysis on (neutral view shows no bar value or lines and the network list shows no analysis request until the answer is shown). **Step 7: Commit** `feat: hide analysis until the guess, accessibility pass and docs`.
