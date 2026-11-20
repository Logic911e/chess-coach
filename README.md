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
- [ ] Chat panel scoped to the selected position (next)
- [ ] pgvector / full-text retrieval of similar past mistakes (later)

## Run the UI

```bash
pip install -e ".[web]"
docker-compose up -d && python -m chess_coach.db      # Postgres + migrations
python -m chess_coach.import_games my_games.pgn       # analyse games with Stockfish
ollama serve                                          # local model, for "Explain this move"
uvicorn chess_coach.api:app --port 8000               # then open http://localhost:8000
```

Pick a game, step through it with the arrow keys, and jump between key moments. The board shows
the position before the move, with the move played and the engine's best move as arrows. The
move strip shows how much each move cost. "Explain this move" asks the local model and caches the
answer in Postgres. There is no chat yet.

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
- The win-probability constant (`k=0.004`) is a placeholder until fitted to data and player rating.
- No full static exchange evaluation; pins on attackers are ignored.
- Forks only look at immediate targets; only absolute pins are detected.

## Licensing

Stockfish is GPL. It is only ever called as an external process and is never bundled.
If datasets such as ChessReD (CC BY-NC-SA 4.0) are used later, this project must stay
**non-commercial**.
- Chess piece images (`src/chess_coach/web/pieces/`) are Colin M.L. Burnett's "Cburnett" set,
  bundled with python-chess and exported by `scripts/export_pieces.py` (GPL v2+ / BSD / GFDL).
