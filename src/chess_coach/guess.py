"""Score a move the user guessed, the same way the analyser scores played moves."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_coach import features as cf
from chess_coach.engine_service import EngineLike


def score_after(after: chess.Board, cp_best: int, depth: int, engine: EngineLike) -> int:
    """Mover's centipawn score for the move that produced `after` (not the engine's best move).

    Terminal positions score MATE_CP (checkmate) or 0; otherwise the opponent's best reply
    is negated and capped at `cp_best`, since no move can beat the best one."""
    if after.is_game_over():
        return cf.MATE_CP if after.is_checkmate() else 0
    return min(cp_best, -engine.analyse(after, depth=depth)[0].cp_capped)


@dataclass
class GuessResult:
    legal: bool
    matched: bool
    classification: str | None
    expected_points_lost: float | None
    san: str | None


def _norm(board: chess.Board, uci: str | None) -> str | None:
    """Standard-form UCI of a legal move (king-takes-rook castling becomes e1g1), else None."""
    if not uci:
        return None
    try:
        return board.parse_uci(uci).uci()
    except ValueError:
        return None


def score_guess(
    fen: str, uci: str, best_uci: str, cp_best: int, depth: int, engine: EngineLike,
    played_uci: str | None = None, cp_played: int | None = None,
) -> GuessResult:
    """`played_uci` and `cp_played` (the stored score of the move actually played) let a guess that
    equals the played move be labelled without asking the engine again."""
    board = chess.Board(fen)
    try:
        move = board.parse_uci(uci)  # also rejects a promotion without its letter
    except ValueError:
        return GuessResult(False, False, None, None, None)
    san = board.san(move)
    norm = move.uci()
    matched = norm == _norm(board, best_uci)
    if matched:
        score = cp_best
    elif cp_played is not None and norm == _norm(board, played_uci):
        score = cp_played
    else:
        board.push(move)
        score = score_after(board, cp_best, depth, engine)
    loss = cf.expected_points_lost(cp_best, score)
    return GuessResult(True, matched, cf.classify(loss), loss, san)
