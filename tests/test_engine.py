import shutil

import chess
import pytest

from chess_coach.engine import (
    Analysis,
    Engine,
    EngineNotFoundError,
    find_stockfish,
    search_limit,
)

needs_sf = pytest.mark.skipif(shutil.which("stockfish") is None, reason="Stockfish not installed")

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def test_missing_binary_gives_install_help(monkeypatch):
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(EngineNotFoundError, match="brew install stockfish"):
        find_stockfish()


def test_bad_env_path_is_reported(monkeypatch):
    monkeypatch.setenv("STOCKFISH_PATH", "/nope/stockfish")
    with pytest.raises(EngineNotFoundError, match="STOCKFISH_PATH"):
        find_stockfish()


def test_cp_capped_orders_mates():
    mate_in_1 = Analysis(cp=None, mate=1, best_move="a1a2", pv=["a1a2"])
    mate_in_3 = Analysis(cp=None, mate=3, best_move="a1a2", pv=["a1a2"])
    mated = Analysis(cp=None, mate=-2, best_move="a1a2", pv=["a1a2"])
    assert mate_in_1.cp_capped > mate_in_3.cp_capped > 1000
    assert mated.cp_capped < -1000


@needs_sf
def test_best_move_in_qh5_position():
    with Engine() as eng:
        (line,) = eng.analyse(chess.Board(QH5), depth=14)
    assert line.best_move == "g7g6"
    assert line.pv[0] == line.best_move


@needs_sf
def test_multipv_returns_requested_lines():
    with Engine() as eng:
        lines = eng.analyse(chess.Board(), depth=10, multipv=3)
    assert len(lines) == 3
    assert len({line.best_move for line in lines}) == 3


@needs_sf
def test_mate_in_one_is_a_mate_score():
    # Scholar's mate: white to play Qxf7#
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    with Engine() as eng:
        (line,) = eng.analyse(board, depth=10)
    assert line.mate == 1 and line.cp is None
    assert line.best_move == "h5f7"


@needs_sf
def test_score_is_from_mover_perspective():
    # Black to move and a queen down: score must be negative for the mover.
    board = chess.Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1")
    with Engine() as eng:
        (line,) = eng.analyse(board, depth=10)
    assert line.cp is not None and line.cp < -500


@needs_sf
def test_context_manager_shuts_engine_down():
    with Engine() as eng:
        inner = eng._engine
        assert inner is not None
    assert eng._engine is None
    with pytest.raises(RuntimeError):
        eng.analyse(chess.Board())


def test_search_limit_combines_depth_and_time():
    limit = search_limit(12, 1.5)
    assert limit.depth == 12
    assert limit.time == 1.5
    assert search_limit(9, None).time is None
    assert search_limit(None, 2.0).depth is None


def test_search_limit_requires_one_limit():
    with pytest.raises(ValueError):
        search_limit(None, None)
