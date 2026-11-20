import threading

import chess
import pytest

from chess_coach.engine_service import EngineBusy, EngineService


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


class GatedEngine(FakeEngine):
    """Each analyse call records its start, then blocks until its gate is opened."""

    version = "Fake 1"

    def __init__(self, log):
        super().__init__(log)
        self.started = []  # tags in the order the engine began them
        self.gates = {}
        self.entered = {}
        self._g = threading.Lock()

    def gate(self, tag):
        with self._g:
            return self.gates.setdefault(tag, threading.Event())

    def entered_event(self, tag):
        with self._g:
            return self.entered.setdefault(tag, threading.Event())

    def analyse(self, board, depth=None, time=None, multipv=1):
        tag = depth  # tests pass a unique depth as the tag
        self.started.append(tag)
        self.entered_event(tag).set()
        assert self.gate(tag).wait(5)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("boom")
        return []


def make_gated():
    log = {"enter": 0, "exit": 0, "factory": 0}
    engine = GatedEngine(log)

    def factory():
        log["factory"] += 1
        return engine

    return EngineService(factory), engine, log


def run(fn, *args, **kwargs):
    out = {}

    def go():
        try:
            out["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - recorded for the test to assert on
            out["error"] = exc

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t, out


def wait_until(pred, timeout=3.0):
    import time as _t

    end = _t.monotonic() + timeout
    while _t.monotonic() < end:
        if pred():
            return True
        _t.sleep(0.005)
    return False


def test_background_raises_busy_after_max_wait():
    svc, engine, _ = make_gated()
    t1, _ = run(svc.analyse, chess.Board(), 1)
    assert engine.entered_event(1).wait(3)
    with pytest.raises(EngineBusy):
        svc.analyse_background(chess.Board(), 2, max_wait=0.1)
    engine.gate(1).set()
    t1.join(3)
    # the slot is free again: a later background call gets through
    engine.gate(3).set()
    assert svc.analyse_background(chess.Board(), 3, max_wait=2) == []


def test_background_runs_directly_when_engine_idle():
    svc, engine, _ = make_gated()
    engine.gate(1).set()
    assert svc.analyse_background(chess.Board(), 1) == []


def test_newer_background_replaces_waiting_one():
    svc, engine, _ = make_gated()
    t1, _ = run(svc.analyse, chess.Board(), 1)
    assert engine.entered_event(1).wait(3)
    tb1, out1 = run(svc.analyse_background, chess.Board(), 2, max_wait=5)
    assert wait_until(lambda: svc._bg_waiting is not None)
    tb2, out2 = run(svc.analyse_background, chess.Board(), 3, max_wait=5)
    tb1.join(3)
    assert isinstance(out1.get("error"), EngineBusy)  # replaced quickly, engine still busy
    engine.gate(1).set()
    engine.gate(3).set()
    tb2.join(3)
    t1.join(3)
    assert out2.get("value") == []
    assert engine.started == [1, 3]


def test_interactive_goes_before_waiting_background():
    svc, engine, _ = make_gated()
    t1, _ = run(svc.analyse, chess.Board(), 1)
    assert engine.entered_event(1).wait(3)
    tb, outb = run(svc.analyse_background, chess.Board(), 2, max_wait=5)
    assert wait_until(lambda: svc._bg_waiting is not None)
    ti, outi = run(svc.analyse, chess.Board(), 3)
    assert wait_until(lambda: svc._interactive_waiting == 1)
    engine.gate(1).set()
    assert engine.entered_event(3).wait(3)
    assert engine.started == [1, 3]  # background has not jumped the queue
    engine.gate(3).set()
    ti.join(3)
    assert engine.entered_event(2).wait(3)
    engine.gate(2).set()
    tb.join(3)
    t1.join(3)
    assert outi.get("value") == []
    assert outb.get("value") == []
    assert engine.started == [1, 3, 2]


def test_interactive_waits_for_at_most_one_analysis():
    svc, engine, _ = make_gated()
    t1, _ = run(svc.analyse_background, chess.Board(), 1, max_wait=5)
    assert engine.entered_event(1).wait(3)
    tb2, out2 = run(svc.analyse_background, chess.Board(), 2, max_wait=5)
    assert wait_until(lambda: svc._bg_waiting is not None)
    tb3, _ = run(svc.analyse_background, chess.Board(), 3, max_wait=5)  # replaces 2
    ti, outi = run(svc.analyse, chess.Board(), 4)
    assert wait_until(lambda: svc._interactive_waiting == 1)
    engine.gate(1).set()  # the one running analysis finishes
    assert engine.entered_event(4).wait(3)  # the interactive is next, not the queued background
    assert engine.started == [1, 4]
    engine.gate(4).set()
    engine.gate(3).set()
    for t in (t1, tb2, tb3, ti):
        t.join(3)
    assert isinstance(out2.get("error"), EngineBusy)
    assert outi.get("value") == []
    assert engine.started == [1, 4, 3]


def test_engine_failure_in_background_still_restarts_engine():
    svc, engine, log = make_gated()
    engine.gate(1).set()
    engine.fail_next = True
    with pytest.raises(RuntimeError, match="boom"):
        svc.analyse_background(chess.Board(), 1)
    assert log["exit"] == 1
    assert svc.version is None
    assert svc.analyse(chess.Board(), 1) == []
    assert log["factory"] == 2


def test_failure_does_not_wedge_waiters():
    svc, engine, _ = make_gated()
    engine.fail_next = True
    t1, out1 = run(svc.analyse, chess.Board(), 1)
    assert engine.entered_event(1).wait(3)
    tb, outb = run(svc.analyse_background, chess.Board(), 2, max_wait=5)
    assert wait_until(lambda: svc._bg_waiting is not None)
    engine.gate(1).set()
    engine.gate(2).set()
    t1.join(3)
    tb.join(3)
    assert isinstance(out1.get("error"), RuntimeError)
    assert outb.get("value") == []


def test_version_is_none_until_started_then_engine_name():
    svc, engine, _ = make_gated()
    assert svc.version is None
    engine.gate(1).set()
    svc.analyse(chess.Board(), 1)
    assert svc.version == "Fake 1"
