import shutil

import chess
import pytest

from chess_coach.analyser import Thresholds, _net_material_given_up, analyse_game
from chess_coach.engine import Analysis, Engine

needs_sf = pytest.mark.skipif(shutil.which("stockfish") is None, reason="Stockfish not installed")


def _key(board: chess.Board) -> str:
    return f"{board.board_fen()} {board.turn} {board.fullmove_number}"


class ScriptedEngine:
    """Engine stand-in. Scores are mover-perspective centipawns per position."""

    def __init__(self, san_moves, cps, bests):
        # cps/bests: one entry per position, i.e. len(san_moves) + 1 (final entry unused move)
        self.calls = 0
        self.table = {}
        board = chess.Board()
        for i, san in enumerate(san_moves):
            self.table[_key(board)] = (cps[i], bests[i])
            board.push_san(san)
        self.table[_key(board)] = (cps[-1], "a2a3")

    def analyse(self, board, depth=None, time=None, multipv=1):
        self.calls += 1
        cp, best = self.table[_key(board)]
        return [Analysis(cp=cp, mate=None, best_move=best, pv=[best], depth=depth)]


def test_blunder_is_flagged_and_uses_n_plus_one_engine_calls():
    # White's best at move 3 is Nf3 (+400). Qh5 leaves Black +400 (so White is at -400).
    eng = ScriptedEngine(["e4", "e5", "Qh5"], [30, 30, 400, 400], ["e2e4", "e7e5", "g1f3"])
    result = analyse_game("1. e4 e5 2. Qh5", eng)
    assert eng.calls == 4  # 3 moves + the final position
    qh5 = result.moves[2]
    assert (qh5.cp_best, qh5.cp_played) == (400, -400)
    assert qh5.classification == "blunder"
    assert qh5.reasons == ["blunder", "big_swing"]
    assert qh5.facts is not None and qh5.facts["classification"] == "blunder"
    assert [m.san for m in result.key_moments] == ["Qh5"]


def test_quiet_game_has_no_key_moments():
    eng = ScriptedEngine(["e4", "e5"], [30, 30, 30], ["e2e4", "e7e5"])
    result = analyse_game("1. e4 e5", eng)
    assert result.key_moments == []
    assert all(m.facts is None for m in result.moves)


def test_played_move_never_scores_better_than_best():
    # Search noise: next position says Black is only -100, i.e. White "+100" after 1.e4 while
    # the engine's best was +30. cp_played must be capped at cp_best.
    eng = ScriptedEngine(["e4", "e5"], [30, -100, 0], ["d2d4", "e7e5"])
    result = analyse_game("1. e4 e5", eng)
    assert result.moves[0].cp_played == 30
    assert result.moves[0].classification == "best" or result.moves[0].expected_points_lost == 0


def test_threshold_override_flags_a_small_loss():
    eng = ScriptedEngine(["e4", "e5"], [100, -30, 0], ["d2d4", "e7e5"])
    default = analyse_game("1. e4 e5", eng)
    assert default.key_moments == []
    strict = analyse_game("1. e4 e5", eng, thresholds=Thresholds(mistake_loss=0.01, swing=2.0))
    assert [m.san for m in strict.key_moments] == ["e4"]


def test_empty_pgn_raises():
    with pytest.raises(ValueError):
        analyse_game("", ScriptedEngine([], [0], []))


def test_sacrifice_counts_material_but_even_trade_does_not():
    # Knight takes f7 pawn and the king recaptures: knight (3) for pawn (1) = 2 given up.
    b = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4N3/4P3/8/PPPP1PPP/RNBQKB1R w KQkq - 0 1")
    assert _net_material_given_up(b, chess.Move.from_uci("e5f7"), "e8f7") == 2
    # Bishop takes knight, pawn recaptures: even trade.
    t = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1")
    assert _net_material_given_up(t, chess.Move.from_uci("b5c6"), "d7c6") == 0


@needs_sf
def test_real_engine_flags_nf6_blunder_and_credits_the_mate():
    pgn = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#"
    with Engine() as eng:
        result = analyse_game(pgn, eng, depth=12)
    nf6, mate = result.moves[5], result.moves[6]
    assert nf6.san == "Nf6" and nf6.is_key
    assert nf6.classification in {"mistake", "blunder"}
    assert nf6.facts is not None and nf6.facts["best"]["uci"] == "g7g6"
    assert mate.san == "Qxf7#" and mate.classification == "best"
    assert not mate.is_key
