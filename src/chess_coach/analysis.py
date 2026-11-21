"""Position analysis for the page: White-perspective scores and per-move positions.

The page does no chess logic, so every PV move carries the FEN after it, its SAN and flags.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

import chess

from chess_coach.engine import Analysis

MAX_PV_PLIES = 12
ANALYSIS_TIME_CAP = 3.0


def white_score(a: Analysis, white_to_move: bool) -> dict:
    """The engine scores for the mover; flip to White's perspective."""
    sign = 1 if white_to_move else -1
    return {
        "cp": None if a.cp is None else sign * a.cp,
        "mate": None if a.mate is None else sign * a.mate,
    }


def _game_over(board: chess.Board) -> str | None:
    outcome = board.outcome()
    if outcome is None:
        return None
    if outcome.termination == chess.Termination.CHECKMATE:
        return "checkmate"
    if outcome.termination == chess.Termination.STALEMATE:
        return "stalemate"
    return "draw"


def _moves(board: chess.Board, pv: list[str]) -> list[dict]:
    board = board.copy()
    out: list[dict] = []
    for uci in pv[:MAX_PV_PLIES]:
        try:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
        except ValueError:
            break
        san = board.san(move)
        capture = board.is_capture(move)
        board.push(move)
        out.append({"san": san, "uci": uci, "fen": board.fen(),
                    "capture": capture, "check": board.is_check()})
    return out


def analyse_fen(
    fen: str,
    depth: int,
    lines: int,
    run: Callable[[chess.Board, int, int], list[Analysis]],
    version: str | None = None,
) -> dict:
    """`run(board, depth, lines)` does the engine search (it is not called for a finished game)."""
    board = chess.Board(fen)
    result = _game_over(board)
    if result is not None:
        return {"game_over": True, "result": result}
    found = run(board, depth, lines)
    white = board.turn == chess.WHITE
    reached = found[0].depth if found and found[0].depth is not None else depth
    return {
        "game_over": False,
        "version": version,
        "depth": reached,
        "lines": [{"score": white_score(a, white), "moves": _moves(board, a.pv)} for a in found],
    }


class AnalysisCache:
    """A small thread-safe LRU keyed by the requested (fen, depth, lines)."""

    def __init__(self, max_size: int = 256) -> None:
        self.max_size = max_size
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)
