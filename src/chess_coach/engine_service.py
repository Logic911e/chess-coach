"""One long-lived Stockfish shared by every API request.

Starts lazily on first use and serialises calls with a lock, because a single UCI
process can only run one search at a time.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from typing import Protocol

import chess

from chess_coach.engine import Analysis, Engine


class EngineLike(Protocol):
    def analyse(
        self, board: chess.Board, depth: int | None = None, time: float | None = None,
        multipv: int = 1,
    ) -> list[Analysis]: ...


class EngineService:
    def __init__(
        self, factory: Callable[[], AbstractContextManager[EngineLike]] = Engine
    ) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._stack: ExitStack | None = None
        self._engine: EngineLike | None = None

    def analyse(self, board: chess.Board, depth: int, multipv: int = 1) -> list[Analysis]:
        with self._lock:
            if self._engine is None:
                stack = ExitStack()
                try:
                    self._engine = stack.enter_context(self._factory())
                except BaseException:
                    stack.close()
                    raise
                self._stack = stack
            try:
                return self._engine.analyse(board, depth=depth, multipv=multipv)
            except ValueError:
                raise  # bad input (e.g. game-over position); the engine is still healthy
            except BaseException:
                # Crashed, hung or killed engine: drop it so the next call restarts it.
                self._discard()
                raise

    def _discard(self) -> None:
        stack, self._stack, self._engine = self._stack, None, None
        if stack is not None:
            with contextlib.suppress(Exception):  # closing a dead engine may fail
                stack.close()

    def close(self) -> None:
        with self._lock:
            stack, self._stack, self._engine = self._stack, None, None
        if stack is not None:
            stack.close()
