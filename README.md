# chess-coach

A chess coach chatbot built on one rule: **Stockfish is the source of truth**.
python-chess handles legality and feature extraction, and the language model only
explains facts it is given. It never invents chess analysis.

## Status

Work in progress.

- [x] Feature extraction and move grading (`src/chess_coach/features.py`)
- [x] Stockfish wrapper (`src/chess_coach/engine.py`)
- [x] Game analyser (`src/chess_coach/analyser.py`)
- [x] Explanation prompt + local LLM call (`explainer.py`, `llm.py`, Ollama)
- [x] Evaluation harness (`evaluation.py`, results in `results/`)
- [x] Postgres layer: schema, migrations, indexes chosen with `EXPLAIN ANALYZE` (`docs/query_plans.md`)
- [x] Game review UI: board, key moments, on-demand explanations (`api.py`, `src/chess_coach/web/`)
- [x] Immersive review UI: themes, sound, study mode, guess-first, keyboard shortcuts, accessibility pass
- [x] Chat panel scoped to the selected position
- [ ] Retry queue for explanations that fail the checker (later)
- [ ] Pattern detection across games (later)
- [ ] pgvector / full-text retrieval of similar past mistakes (later)

## Run the UI

```bash
pip install -e ".[web]"
docker-compose up -d && python -m chess_coach.db      # Postgres + migrations
python -m chess_coach.import_games my_games.pgn       # analyse games with Stockfish
ollama serve                                          # local model, for "Explain this move"
uvicorn chess_coach.api:app --port 8000               # then open http://localhost:8000
```

## Using the review page

Open http://localhost:8000. Pick a game with **Games**; the board shows the position before the
selected move, with the move played and the engine's best move as arrows. The strip under the board
shows how much each move cost (taller means more expected points lost).

- **Themes:** the three swatches in the top bar switch between Walnut, Slate and Paper. The choice is
  remembered in this browser.
- **Sound:** Felt (default), Wood or Off, plus a volume slider. Nothing plays before your first click or key press.
- **Study mode:** removes all sound and motion. The page does the same when your system asks for reduced motion.
- **Keyboard:** Left/Right step through moves, `j`/`k` jump to the next/previous key moment, `g` starts a
  guess, `/` opens the chat, `m` mutes or unmutes, `?` lists the shortcuts, Esc closes a panel.
- **Guess first:** on a key moment you played, "Guess first" hides the label, arrows and explanation. Click the
  piece you would move, then the square. The engine scores your move and then reveals the answer.
- **Chat:** "Ask the coach" asks the local model about the position on screen. History is dropped when you
  change move, and chat is off during a guess so an answer cannot give the move away.
- **Which player are you:** guess-first needs to know which player is you. The server may suggest one;
  if it does not and you have not chosen, the page asks once (a dismissed prompt is not shown again on load).
  The answer is remembered in this browser only and can be changed from the `?` dialog. No name is hard-coded
  in the repository.
- **Screen readers:** the move strip is one tab stop, each bar has an accessible name, and there is a
  visually hidden list of all moves ("11. Qb3, mistake") whose buttons jump to a move. The move name and label
  sit in a polite live region, and only the coach's chat answers are announced, not your own messages. During
  a guess the current move is named "your move" only. What has and has not been checked is under Known limits.

"Explain this move" asks the local model and caches the answer in Postgres.

Tests:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
node --test tests/web/*.test.mjs        # front-end logic (use the glob; the bare directory form fails on some Node versions)
```

## Result so far (small sample, read the caveats)

Local `qwen2.5:7b-instruct`, 12 positions x 3 samples at temperature 0.5. "False claim" means an
automatic check found an illegal move, a piece on a square that never holds it, or a forbidden
phrase. Automatic counts from the second run (`results/eval_..._20261120_114204.json`):

| Prompt given to the model | Responses with a checked false claim |
|---|---|
| FEN + move only | 8/36 |
| Facts as raw JSON | 4/36 |
| Facts as plain-English statements (`narrative.py`) | 0/36 |

**Read this carefully.** The checker only sees moves and piece placement. Reading 12 of the 36
"statements" responses by hand found errors it cannot see: a pin described backwards, saying the
engine "prefers" a move when that was the move played, and a passed-pawn statement misused. So the
statements prompt removes the *checkable* errors, but this run does **not** show it is more
faithful overall. The flagged responses in the second run have not been manually reviewed, and
the samples are small and not independent. Details and the first run's manual review:
`results/REVIEW.md`.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Stockfish is needed from the engine step onward (`brew install stockfish` on macOS).

Database (Docker, Postgres 17; uses port 5433 so it never clashes with a local Postgres):

```bash
cp .env.example .env            # then set a real POSTGRES_PASSWORD
docker-compose up -d
PYTHONPATH=src python -m chess_coach.db        # applies migrations/*.sql in order
```

Analyse real games and store them (skips games already stored; add `--explain` to also write
explanations for key moments with the local model):

```bash
PYTHONPATH=src python -m chess_coach.import_games data/sample_games.pgn --depth 14
PYTHONPATH=src python -m chess_coach.import_games games.pgn --depth 14 --explain
```

`data/sample_games.pgn` holds the public-domain Opera Game (Morphy, 1858) and a short illustrative
trap game that I wrote, not a real game.

Local model for explanations: `brew install ollama && ollama serve` and `ollama pull qwen2.5:7b-instruct`.

## Known limits

- The explanation guardrail checks two things: named moves must be legal, and "<piece> on <square>"
  claims (including lists like "pawns on e4 and h5") must match a real position. It does NOT check
  relational claims such as "undefended", "pinned" or "attacked", or wrong verdicts. In a live test
  of six samples for the same blunder (`...Nf6` into `Qxf7#`), all six passed and all six contained
  errors of that kind, for example "the f7 pawn was already pinned", "Knight to g6" (g6 is a pawn
  move) and the white queen described as "undefended on h5".
- Chat and explanations come from a small local model and are checked only for illegal moves and wrong
  piece squares, so they can still be wrong or vague.
- Sounds and animation were only checked structurally (the code and tests); nobody listened to them or judged
  the motion by eye on every theme.
- Accessibility has had only a structural pass, not a test with a real screen reader. In Chrome I inspected
  the accessibility tree for the move list, strip and live regions in the Walnut theme, checked in the page
  that the move names are neutral during a guess, ran the chat announcement against a faked server reply, and
  saw the focus outline on the strip bar in Slate and Paper. Beyond that: the neutral names are otherwise covered
  by unit tests, the outline colours by a computed-contrast test, and the small-screen layout was measured at
  320px wide and 300px tall but not looked at on a real phone.
- Guess-first needs the engine and takes a few seconds to score a guess.
- There is no keyboard-only way to pick squares during a guess yet; it needs the mouse or touch.
- The win-probability constant (`k=0.004`) is a placeholder until fitted to data and player rating.
- No full static exchange evaluation; pins on attackers are ignored.
- Forks only look at immediate targets; only absolute pins are detected.

## Licensing

Stockfish is GPL. It is only ever called as an external process and is never bundled.
If datasets such as ChessReD (CC BY-NC-SA 4.0) are used later, this project must stay
**non-commercial**.
- Chess piece images (`src/chess_coach/web/pieces/`) are the "chessnut" set by Alexis Luengas,
  Apache License 2.0, unmodified, taken from the Lichess repository. Licence text and source are in
  `src/chess_coach/web/pieces/LICENSE.txt`.
