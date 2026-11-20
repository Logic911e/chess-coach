import threading

import chess
import pytest

from chess_coach.engine_service import EngineService


class FakeEngine:
    def __init__(self, log):
        self.log = log
        self.inside = 0
        self.max_inside = 0
        self.fail_next = False
        self._guard = threading.Lock()

    def __enter__(self):
        self.log["enter"] += 1
        return self

    def __exit__(self, *exc):
        self.log["exit"] += 1

    def analyse(self, board, depth=None, time=None, multipv=1):
        with self._guard:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        try:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("boom")
            import time as _t

            _t.sleep(0.05)
            return []
        finally:
            with self._guard:
                self.inside -= 1


def make():
    log = {"enter": 0, "exit": 0, "factory": 0}
    engine = FakeEngine(log)

    def factory():
        log["factory"] += 1
        return engine

    return EngineService(factory), engine, log


def test_starts_lazily_and_only_once():
    svc, _, log = make()
    assert log["factory"] == 0
    svc.analyse(chess.Board(), depth=1)
    svc.analyse(chess.Board(), depth=1)
    assert log["factory"] == 1
    assert log["enter"] == 1


def test_calls_are_serialised():
    svc, engine, _ = make()
    threads = [
        threading.Thread(target=svc.analyse, args=(chess.Board(), 1)) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert engine.max_inside == 1


def test_close_is_idempotent_and_releases_engine():
    svc, _, log = make()
    svc.analyse(chess.Board(), depth=1)
    svc.close()
    svc.close()
    assert log["exit"] == 1


def test_close_without_start_is_safe():
    svc, _, log = make()
    svc.close()
    assert log["exit"] == 0


def test_error_in_engine_releases_lock():
    svc, engine, _ = make()
    svc.analyse(chess.Board(), depth=1)
    engine.fail_next = True
    with pytest.raises(RuntimeError):
        svc.analyse(chess.Board(), depth=1)
    done = []
    t = threading.Thread(target=lambda: done.append(svc.analyse(chess.Board(), depth=1)))
    t.start()
    t.join(timeout=2)
    assert done == [[]]


def test_app_closes_engine_service_on_shutdown():
    from fastapi.testclient import TestClient

    from chess_coach.api import create_app

    svc, _, log = make()
    app = create_app(engine_service=svc)
    assert app.state.engine is svc
    with TestClient(app):
        svc.analyse(chess.Board(), depth=1)
    assert log["exit"] == 1


def test_engine_failure_discards_engine_and_restarts_on_next_call():
    svc, engine, log = make()
    svc.analyse(chess.Board(), depth=1)
    assert log["factory"] == 1
    engine.fail_next = True
    with pytest.raises(RuntimeError, match="boom"):
        svc.analyse(chess.Board(), depth=1)
    assert log["exit"] == 1  # dead engine was torn down
    assert svc.analyse(chess.Board(), depth=1) == []
    assert log["factory"] == 2
    assert log["enter"] == 2


def test_teardown_error_does_not_mask_original_failure():
    svc, engine, log = make()
    svc.analyse(chess.Board(), depth=1)
    engine.fail_next = True

    def bad_exit(*exc):
        raise OSError("pipe closed")

    engine.__class__.__exit__, orig = bad_exit, engine.__class__.__exit__
    try:
        with pytest.raises(RuntimeError, match="boom"):
            svc.analyse(chess.Board(), depth=1)
    finally:
        engine.__class__.__exit__ = orig
    assert svc.analyse(chess.Board(), depth=1) == []
    assert log["factory"] == 2
