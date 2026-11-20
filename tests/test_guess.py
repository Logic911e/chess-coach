import chess

from chess_coach.engine import Analysis
from chess_coach.features import MATE_CP, classify, expected_points_lost
from chess_coach.guess import score_guess

START = chess.STARTING_FEN


class Fake:
    """Returns a fixed score for the side to move in whatever position it is asked about."""

    def __init__(self, cp=0):
        self.cp, self.calls = cp, 0

    def analyse(self, board, depth=None, time=None, multipv=1):
        self.calls += 1
        mv = next(iter(board.legal_moves)).uci()
        return [Analysis(cp=self.cp, mate=None, best_move=mv, pv=[mv], depth=depth)]


def test_exact_best_move_matches_without_engine_call():
    eng = Fake()
    r = score_guess(START, "e2e4", "e2e4", 30, 12, eng)
    assert (r.legal, r.matched, r.classification, r.expected_points_lost, r.san) == (
        True, True, "best", 0.0, "e4")
    assert eng.calls == 0


def test_alternative_move_is_scored_by_engine():
    eng = Fake(cp=100)  # opponent is +100 after the guess, so the guess is worth -100
    r = score_guess(START, "a2a3", "e2e4", 30, 12, eng)
    loss = expected_points_lost(30, min(30, -100))
    assert r.legal and not r.matched and eng.calls == 1
    assert r.expected_points_lost == loss and r.classification == classify(loss)
    assert r.san == "a3"


def test_illegal_move_is_not_scored():
    eng = Fake()
    for bad in ("e2e5", "zzzz", ""):
        r = score_guess(START, bad, "e2e4", 30, 12, eng)
        assert (r.legal, r.matched, r.classification, r.expected_points_lost, r.san) == (
            False, False, None, None, None)
    assert eng.calls == 0


def test_promotion_without_letter_is_illegal():
    fen = "8/4P1k1/8/8/8/8/8/K7 w - - 0 1"
    eng = Fake()
    assert score_guess(fen, "e7e8", "e7e8q", 500, 12, eng).legal is False
    assert score_guess(fen, "e7e8q", "e7e8q", 500, 12, eng).legal is True


def test_checkmating_guess_scores_as_win_without_engine():
    fen = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
    eng = Fake()
    r = score_guess(fen, "a1a8", "a1a8", MATE_CP, 12, eng)
    assert r.expected_points_lost == 0 and r.classification == "best" and r.san == "Ra8#"
    # also when it is not the stored best move
    r = score_guess(fen, "a1a8", "e1d2", MATE_CP, 12, eng)
    assert not r.matched and r.expected_points_lost == 0 and r.classification == "best"
    assert eng.calls == 0


def test_stalemating_guess_scores_zero():
    fen = "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1"  # Qg6 stalemates
    eng = Fake()
    r = score_guess(fen, "g1g6", "g1a7", 900, 12, eng)
    assert r.legal and not r.matched and eng.calls == 0
    assert r.expected_points_lost == expected_points_lost(900, 0)
    assert r.classification == "blunder"


CASTLE = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"


def test_castling_matches_in_either_encoding():
    for guess in ("e1g1", "e1h1"):
        for best in ("e1g1", "e1h1"):
            eng = Fake()
            r = score_guess(CASTLE, guess, best, 30, 12, eng)
            assert r.legal and r.matched and r.san == "O-O" and r.classification == "best"
            assert eng.calls == 0
    r = score_guess(CASTLE, "e1c1", "e1g1", 30, 12, Fake())
    assert r.legal and not r.matched and r.san == "O-O-O"


def test_guessing_the_played_move_uses_stored_score_without_engine():
    eng = Fake(cp=999)
    r = score_guess(START, "a2a3", "e2e4", 30, 12, eng, played_uci="a2a3", cp_played=-100)
    loss = expected_points_lost(30, -100)
    assert eng.calls == 0 and not r.matched
    assert r.expected_points_lost == loss and r.classification == classify(loss)
