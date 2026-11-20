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


def score_guess(
    fen: str, uci: str, best_uci: str, cp_best: int, depth: int, engine: EngineLike
) -> GuessResult:
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return GuessResult(False, False, None, None, None)
    if move not in board.legal_moves:  # also rejects a promotion without its letter
        return GuessResult(False, False, None, None, None)
    san = board.san(move)
    if uci == best_uci:
        cp_played = cp_best
    else:
        board.push(move)
        cp_played = score_after(board, cp_best, depth, engine)
    loss = cf.expected_points_lost(cp_best, cp_played)
    return GuessResult(True, uci == best_uci, cf.classify(loss), loss, san)
