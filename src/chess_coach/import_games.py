"""Analyse every game in a PGN file with Stockfish and store the results in Postgres.

    python -m chess_coach.import_games data/sample_games.pgn --depth 14
    python -m chess_coach.import_games games.pgn --explain      # also write explanations

Games already in the database are skipped before any engine time is spent on them.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import chess.engine
import chess.pgn
import psycopg

from chess_coach import db
from chess_coach.analyser import GameAnalysis, SupportsAnalyse, analyse_game
from chess_coach.engine import DEFAULT_DEPTH, Engine
from chess_coach.explainer import explain
from chess_coach.llm import ChatClient, OllamaClient
from chess_coach.store import game_hash, save_explanation, save_game


@dataclass
class ImportSummary:
    imported: int = 0
    skipped_duplicate: int = 0
    failed: list[str] = field(default_factory=list)  # "<white> vs <black>: reason"
    key_moments: int = 0
    explanations: int = 0
    flagged_explanations: int = 0


def iter_games(path: Path):
    """Yield (headers, pgn_text, uci_moves) for each game in a PGN file."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        while (game := chess.pgn.read_game(handle)) is not None:
            text = game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=True))
            yield dict(game.headers), text, [m.uci() for m in game.mainline_moves()]


def iter_games_text(text: str):
    """Like iter_games, for PGN text that is already in memory."""
    import io
    handle = io.StringIO(text)
    while (game := chess.pgn.read_game(handle)) is not None:
        out = game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=True))
        yield dict(game.headers), out, [m.uci() for m in game.mainline_moves()]


def explain_key_moments(
    conn: psycopg.Connection, game_id: int, analysis: GameAnalysis, client: ChatClient,
    summary: ImportSummary,
) -> None:
    for rec in analysis.key_moments:
        assert rec.facts is not None
        move_id = conn.execute(
            "SELECT id FROM moves WHERE game_id = %s AND ply = %s", (game_id, rec.ply)
        ).fetchone()[0]  # type: ignore[index]
        result = explain(rec.facts, client, best_line_uci=rec.best_line_uci)
        save_explanation(conn, move_id, client.model, result.text, result.flagged, result.attempts)
        summary.explanations += 1
        summary.flagged_explanations += result.flagged
    conn.commit()


def import_pgn(
    conn: psycopg.Connection,
    path: Path,
    engine: SupportsAnalyse,
    engine_version: str,
    depth: int = DEFAULT_DEPTH,
    client: ChatClient | None = None,
    max_games: int | None = None,
    log=print,
    *,
    pgn_text: str | None = None,
    source_account: int | None = None,
    should_stop=lambda: False,
) -> ImportSummary:
    """Import the games in `path`, or in `pgn_text` when given. Games from a linked account carry
    its id. `should_stop()` is checked between games so an import can be cancelled."""
    summary = ImportSummary()
    games = iter_games_text(pgn_text) if pgn_text is not None else iter_games(path)
    for n, (headers, text, ucis) in enumerate(games, start=1):
        if (max_games is not None and n > max_games) or should_stop():
            break
        label = f"{headers.get('White', '?')} vs {headers.get('Black', '?')}"
        if not ucis:
            summary.failed.append(f"{label}: no moves")
            continue
        exists = conn.execute(
            "SELECT 1 FROM games WHERE pgn_hash = %s", (game_hash(headers, ucis),)
        ).fetchone()
        if exists:
            summary.skipped_duplicate += 1
            log(f"[{n}] {label}: already stored, skipped")
            continue
        try:
            analysis = analyse_game(text, engine, depth=depth)
            game_id = save_game(conn, text, analysis, depth, engine_version)
            if game_id is not None and source_account is not None:
                conn.execute("UPDATE games SET source_account = %s WHERE id = %s",
                             (source_account, game_id))
            conn.commit()
        except (ValueError, RuntimeError, psycopg.Error, chess.engine.EngineError) as e:
            # keep going: one bad game must not lose the rest of the file
            conn.rollback()
            summary.failed.append(f"{label}: {type(e).__name__}: {e}")
            log(f"[{n}] {label}: FAILED ({e})")
            continue
        if game_id is None:  # lost a race with another importer
            summary.skipped_duplicate += 1
            continue
        summary.imported += 1
        summary.key_moments += len(analysis.key_moments)
        log(f"[{n}] {label}: {len(analysis.moves)} moves, {len(analysis.key_moments)} key moments")
        if client is not None:
            explain_key_moments(conn, game_id, analysis, client, summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pgn", type=Path)
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--explain", action="store_true", help="explain key moments with the local model")
    ap.add_argument("--model", default=None, help="Ollama model (default: CHESS_COACH_MODEL or qwen2.5:7b-instruct)")
    a = ap.parse_args()
    if not a.pgn.is_file():
        raise SystemExit(f"No such file: {a.pgn}")
    client = OllamaClient(model=a.model) if a.explain else None
    with db.connect() as conn, Engine() as engine:
        s = import_pgn(conn, a.pgn, engine, engine.version, a.depth, client, a.max_games)
    print(
        f"\nimported {s.imported}, skipped {s.skipped_duplicate} duplicates, failed {len(s.failed)}; "
        f"{s.key_moments} key moments, {s.explanations} explanations ({s.flagged_explanations} flagged)"
    )
    for f in s.failed:
        print("  FAILED:", f)


if __name__ == "__main__":
    main()
