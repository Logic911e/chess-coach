"""Save an analysed game into Postgres."""

from __future__ import annotations

import hashlib
import io
import json
import re

import chess
import chess.pgn
import psycopg

from chess_coach.analyser import GameAnalysis, MoveRecord

PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
OPENING_PLIES = 20  # the first 10 moves each
ENDGAME_NONPAWN_MATERIAL = 13  # both sides together, e.g. a rook and a minor piece each


def phase_of(fen: str, ply: int) -> str:
    """opening: first 10 moves. endgame: little non-pawn material left. Otherwise middlegame."""
    if ply <= OPENING_PLIES:
        return "opening"
    board = chess.Board(fen)
    material = sum(
        value * len(board.pieces(piece, color))
        for piece, value in PIECE_VALUES.items()
        for color in (chess.WHITE, chess.BLACK)
    )
    return "endgame" if material <= ENDGAME_NONPAWN_MATERIAL else "middlegame"


def game_hash(headers: dict[str, str], uci_moves: list[str]) -> str:
    """Hash of who played what, so re-importing the same game is detected."""
    key = "|".join(
        [headers.get("White", "?"), headers.get("Black", "?"), headers.get("Date", "?"), *uci_moves]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _date(value: str | None) -> str | None:
    m = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", value or "")
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def save_game(
    conn: psycopg.Connection,
    pgn: str,
    analysis: GameAnalysis,
    engine_depth: int,
    engine_version: str,
) -> int | None:
    """Insert the game, its moves, evaluations and facts in one transaction.

    Returns the new game id, or None if this game was already stored.
    """
    h = analysis.headers
    eco = h.get("ECO") if re.fullmatch(r"[A-E][0-9]{2}", h.get("ECO", "")) else None
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO games (white, black, result, eco, opening, played_on, pgn, pgn_hash)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (pgn_hash) DO NOTHING RETURNING id",
            (
                h.get("White", "?"),
                h.get("Black", "?"),
                h.get("Result", "*") if h.get("Result") in ("1-0", "0-1", "1/2-1/2") else "*",
                eco,
                h.get("Opening"),
                _date(h.get("Date")),
                pgn,
                game_hash(h, [m.uci for m in analysis.moves]),
            ),
        ).fetchone()
        if row is None:
            return None
        game_id = row[0]
        for m in analysis.moves:
            _save_move(conn, game_id, m, engine_depth, engine_version)
    return game_id


def _save_move(
    conn: psycopg.Connection, game_id: int, m: MoveRecord, depth: int, engine_version: str
) -> None:
    move_id = conn.execute(
        "INSERT INTO moves (game_id, ply, move_number, color, san, uci, fen_before, phase)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (game_id, m.ply, m.move_number, m.color, m.san, m.uci, m.fen_before,
         phase_of(m.fen_before, m.ply)),
    ).fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO evaluations VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (move_id, m.best_uci, m.cp_best, m.cp_played, m.expected_points_lost, m.classification,
         depth, engine_version),
    )
    if m.facts is not None:
        conn.execute(
            "INSERT INTO facts (move_id, facts, reasons) VALUES (%s,%s,%s)",
            (move_id, json.dumps(m.facts), m.reasons),
        )


def save_explanation(
    conn: psycopg.Connection, move_id: int, model: str, body: str, flagged: bool, attempts: int
) -> int:
    row = conn.execute(
        "INSERT INTO explanations (move_id, model, body, flagged, attempts)"
        " VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (move_id, model, body, flagged, attempts),
    ).fetchone()
    assert row is not None
    return int(row[0])


def read_game(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("No game found in PGN.")
    return game
