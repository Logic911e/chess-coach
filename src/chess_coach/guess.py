"""Score a move the user guessed, the same way the analyser scores played moves."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_coach import features as cf
from chess_coach.engine_service import EngineLike


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
        if board.is_game_over():
            cp_played = cf.MATE_CP if board.is_checkmate() else 0
        else:
            cp_played = min(cp_best, -engine.analyse(board, depth=depth)[0].cp_capped)
    loss = cf.expected_points_lost(cp_best, cp_played)
    return GuessResult(True, uci == best_uci, cf.classify(loss), loss, san)
