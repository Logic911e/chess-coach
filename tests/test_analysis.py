import chess

from chess_coach.analysis import AnalysisCache, analyse_fen, white_score
from chess_coach.engine import Analysis

START = chess.STARTING_FEN


def an(cp=0, mate=None, pv=(), depth=10):
    return Analysis(cp=cp, mate=mate, best_move=pv[0] if pv else "", pv=list(pv), depth=depth)


class Run:
    def __init__(self, lines):
        self.lines, self.calls = lines, []

    def __call__(self, board, depth, lines):
        self.calls.append((board.fen(), depth, lines))
        return self.lines


def test_white_score_flips_cp_when_black_to_move():
    assert white_score(an(cp=40), True) == {"cp": 40, "mate": None}
    assert white_score(an(cp=40), False) == {"cp": -40, "mate": None}


def test_white_score_flips_mate_sign_when_black_to_move():
    assert white_score(an(cp=None, mate=3), True) == {"cp": None, "mate": 3}
    assert white_score(an(cp=None, mate=3), False) == {"cp": None, "mate": -3}
    assert white_score(an(cp=None, mate=-2), False) == {"cp": None, "mate": 2}


def test_pv_positions_and_flags():
    # 1.e4 d5 2.exd5 ... ; then a mating line from a separate position
    r = analyse_fen(START, 10, 1, Run([an(pv=["e2e4", "d7d5", "e4d5"])]))
    moves = r["lines"][0]["moves"]
    assert [m["san"] for m in moves] == ["e4", "d5", "exd5"]
    assert [m["capture"] for m in moves] == [False, False, True]
    b = chess.Board()
    for m, u in zip(moves, ["e2e4", "d7d5", "e4d5"], strict=True):
        b.push_uci(u)
        assert m["uci"] == u and m["fen"] == b.fen()
    mate = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
    r = analyse_fen(mate, 10, 1, Run([an(cp=None, mate=1, pv=["a1a8"])]))
    m = r["lines"][0]["moves"][0]
    assert m["san"] == "Ra8#" and m["check"] is True and m["capture"] is False


def test_en_passant_counts_as_capture():
    fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
    r = analyse_fen(fen, 10, 1, Run([an(pv=["e5d6"])]))
    assert r["lines"][0]["moves"][0]["capture"] is True


def test_pv_is_capped_at_12_plies():
    pv = ["g1f3", "g8f6", "f3g1", "f6g8"] * 5
    r = analyse_fen(START, 10, 1, Run([an(pv=pv)]))
    assert len(r["lines"][0]["moves"]) == 12


def test_game_over_has_no_engine_call():
    run = Run([an()])
    cases = {
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1": "stalemate",
        "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1": None,
        "R5k1/5ppp/8/8/8/8/8/4K3 b - - 0 1": "checkmate",
        "8/8/8/4k3/8/8/8/4K3 w - - 0 1": "draw",
    }
    for fen, result in cases.items():
        if result is None:
            continue
        assert analyse_fen(fen, 10, 1, run) == {"game_over": True, "result": result}
    assert run.calls == []


def test_reached_depth_is_reported():
    r = analyse_fen(START, 16, 2, Run([an(pv=["e2e4"], depth=11), an(pv=["d2d4"], depth=10)]),
                    version="SF 17")
    assert r["depth"] == 11 and r["game_over"] is False and r["version"] == "SF 17"
    assert len(r["lines"]) == 2


def test_cache_returns_stored_result_without_engine_call():
    cache, run = AnalysisCache(), Run([an(pv=["e2e4"])])
    key = (START, 16, 3)
    assert cache.get(key) is None
    value = analyse_fen(START, 16, 3, run)
    cache.set(key, value)
    assert cache.get(key) == value
    assert len(run.calls) == 1


def test_cache_evicts_least_recently_used():
    cache = AnalysisCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1  # a is now most recent
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_garbage_or_illegal_pv_move_stops_gracefully():
    for bad in ("zzzz", "e2e5", "a1a1"):
        r = analyse_fen(START, 10, 1, Run([an(pv=["e2e4", bad, "d7d5"])]))
        assert [m["uci"] for m in r["lines"][0]["moves"]] == ["e2e4"]


def test_pv_with_castling_and_promotion():
    fen = "r3k2r/P7/8/8/8/8/8/R3K2R w KQkq - 0 1"
    r = analyse_fen(fen, 10, 1, Run([an(pv=["e1g1", "e8c8", "a7a8q"])]))
    moves = r["lines"][0]["moves"]
    b = chess.Board(fen)
    for m, u in zip(moves, ["e1g1", "e8c8", "a7a8q"], strict=True):
        san = b.san(chess.Move.from_uci(u))
        b.push_uci(u)
        assert m["san"] == san and m["fen"] == b.fen() and m["check"] == b.is_check()
    assert [m["san"] for m in moves][:2] == ["O-O", "O-O-O"]
    assert moves[2]["san"] == "a8=Q+" and moves[2]["capture"] is False
    assert moves[2]["check"] is True


def test_black_to_move_mate_is_negative_for_white_through_analyse_fen():
    # Black to move and mates in 1 (...Ra1#): mover's mate +1 becomes White -1.
    fen = "6k1/8/8/8/8/5q2/6r1/7K b - - 0 1"
    r = analyse_fen(fen, 10, 1, Run([an(cp=None, mate=1, pv=["f3f1"])]))
    assert r["lines"][0]["score"] == {"cp": None, "mate": -1}
