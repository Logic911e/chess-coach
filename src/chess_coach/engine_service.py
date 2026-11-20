"""One long-lived Stockfish shared by every API request.

Starts lazily on first use and serialises calls with a lock, because a single UCI
process can only run one search at a time.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from time import monotonic
from typing import Protocol

import chess

from chess_coach.engine import Analysis, Engine


class EngineLike(Protocol):
    def analyse(
        self, board: chess.Board, depth: int | None = None, time: float | None = None,
        multipv: int = 1,
    ) -> list[Analysis]: ...


class EngineBusy(RuntimeError):
    """A background analysis could not get the engine (timed out or was replaced)."""


class EngineService:
    """Shared engine with a contention policy.

    One analysis runs at a time. Interactive callers (`analyse`) wait their turn but always
    go before a waiting background call. At most one background call waits; a newer one
    replaces it. So an interactive call waits for at most one running analysis, never for
    a queue of background ones.
    """

    def __init__(
        self, factory: Callable[[], AbstractContextManager[EngineLike]] = Engine
    ) -> None:
        self._factory = factory
        self._cond = threading.Condition()
        self._running = False
        self._interactive_waiting = 0
        self._bg_waiting: object | None = None  # token of the single waiting background call
        self._stack: ExitStack | None = None
        self._engine: EngineLike | None = None
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        return self._version

    def analyse(
        self, board: chess.Board, depth: int | None, multipv: int = 1, time: float | None = None
    ) -> list[Analysis]:
        with self._cond:
            self._interactive_waiting += 1
            try:
                while self._running:
                    self._cond.wait()
            finally:
                self._interactive_waiting -= 1
            self._running = True
        return self._run(board, depth, multipv, time)

    def analyse_background(
        self,
        board: chess.Board,
        depth: int | None,
        multipv: int = 1,
        time: float | None = None,
        max_wait: float = 2.0,
    ) -> list[Analysis]:
        token = object()
        deadline = monotonic() + max_wait
        with self._cond:
            if self._bg_waiting is not None:
                self._cond.notify_all()  # wakes the replaced call, which sees it lost the slot
            self._bg_waiting = token
            try:
                while True:
                    if self._bg_waiting is not token:
                        raise EngineBusy("superseded by a newer analysis")
                    if not self._running and self._interactive_waiting == 0:
                        self._running = True
                        break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise EngineBusy("engine busy")
                    self._cond.wait(remaining)
            finally:
                if self._bg_waiting is token:
                    self._bg_waiting = None
        return self._run(board, depth, multipv, time)

    def _run(
        self, board: chess.Board, depth: int | None, multipv: int, time: float | None
    ) -> list[Analysis]:
        """Use the engine; the caller has set `_running`. Always releases it."""
        try:
            if self._engine is None:
                stack = ExitStack()
                try:
                    self._engine = stack.enter_context(self._factory())
                except BaseException:
                    stack.close()
                    raise
                self._stack = stack
                name = getattr(self._engine, "version", None)
                self._version = str(name) if name is not None else None
            try:
                return self._engine.analyse(board, depth=depth, time=time, multipv=multipv)
            except ValueError:
                raise  # bad input (e.g. game-over position); the engine is still healthy
            except BaseException:
                # Crashed, hung or killed engine: drop it so the next call restarts it.
                self._discard()
                raise
        finally:
            with self._cond:
                self._running = False
                self._cond.notify_all()

    def _discard(self) -> None:
        stack, self._stack, self._engine, self._version = self._stack, None, None, None
        if stack is not None:
            with contextlib.suppress(Exception):  # closing a dead engine may fail
                stack.close()

    def close(self) -> None:
        with self._cond:
            while self._running:
                self._cond.wait()
            stack, self._stack, self._engine = self._stack, None, None
            self._version = None
        if stack is not None:
            stack.close()
