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
- [ ] pgvector / full-text retrieval of similar past mistakes (later)

## Result so far (small sample, read the caveats)

Local `qwen2.5:7b-instruct`, 12 positions x 3 samples. Responses with at least one objectively
false claim (an illegal move or a piece on the wrong square), after reading each flagged one:
**2/36 with engine facts vs 8/36 with only the FEN and move.** The checker misses wrong verdicts,
so the real gap is probably larger. Full detail and limits: `results/REVIEW.md`.

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
