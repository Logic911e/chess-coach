"""Thin wrapper around a local Stockfish process (UCI).

Stockfish is GPL, so we only ever launch it as an external process. We never
bundle or import its code. Scores are always from the side to move's perspective.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import chess
import chess.engine

DEFAULT_DEPTH = 18
# Used only when a forced mate has to be squeezed into a centipawn number.
MATE_CP = 10_000

INSTALL_HELP = (
    "Stockfish was not found. Install it, or set STOCKFISH_PATH to the binary:\n"
    "  macOS:   brew install stockfish\n"
    "  Linux:   sudo apt install stockfish\n"
    "  Windows: download from https://stockfishchess.org/download/ and set STOCKFISH_PATH"
)


class EngineNotFoundError(RuntimeError):
    """Raised when no Stockfish binary can be located."""


@dataclass(frozen=True)
class Analysis:
    """One principal variation, scored for the side to move."""

    cp: int | None  # centipawns, None when the score is a forced mate
    mate: int | None  # moves to mate: >0 mover mates, <0 mover is mated, None otherwise
    best_move: str  # first move of the PV, UCI
    pv: list[str]  # principal variation, UCI
    depth: int | None = None

    @property
    def cp_capped(self) -> int:
        """Centipawns with mate mapped to +/-MATE_CP (closer mates score slightly higher)."""
        if self.mate is None:
            assert self.cp is not None
            return self.cp
        sign = 1 if self.mate > 0 else -1
        return sign * (MATE_CP - abs(self.mate))


def find_stockfish() -> str:
    """Locate the binary: STOCKFISH_PATH first, then PATH."""
    env = os.environ.get("STOCKFISH_PATH")
    if env:
        if os.path.isfile(env) and os.access(env, os.X_OK):
            return env
        raise EngineNotFoundError(f"STOCKFISH_PATH={env!r} is not an executable file.\n{INSTALL_HELP}")
    found = shutil.which("stockfish")
    if found:
        return found
    raise EngineNotFoundError(INSTALL_HELP)


class Engine:
    """Context manager: `with Engine() as eng: eng.analyse(board)`."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or find_stockfish()
        self._engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> Self:
        self._engine = chess.engine.SimpleEngine.popen_uci(self._path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.quit()
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, TimeoutError):
            # Engine hung or already died: force the process closed.
            self._engine.close()
        finally:
            self._engine = None

    def analyse(
        self,
        board: chess.Board,
        depth: int | None = None,
        time: float | None = None,
        multipv: int = 1,
    ) -> list[Analysis]:
        """Return up to `multipv` lines, best first. Time limit wins over depth if given."""
        if self._engine is None:
            raise RuntimeError("Engine is not running; use it as a context manager.")
        if board.is_game_over():
            raise ValueError("Position is already game over; nothing to analyse.")
        if time is not None:
            limit = chess.engine.Limit(time=time)
        else:
            limit = chess.engine.Limit(depth=depth or DEFAULT_DEPTH)

        infos = self._engine.analyse(board, limit, multipv=multipv)
        if isinstance(infos, dict):  # defensive: single-PV result shape
            infos = [infos]

        results = []
        for info in infos:
            pv = [m.uci() for m in info.get("pv", [])]
            if not pv:
                continue
            # relative = from the side to move's point of view
            score = info["score"].relative
            results.append(
                Analysis(
                    cp=None if score.is_mate() else score.score(),
                    mate=score.mate() if score.is_mate() else None,
                    best_move=pv[0],
                    pv=pv,
                    depth=info.get("depth"),
                )
            )
        return results
