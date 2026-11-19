import chess

from chess_coach.analyser import analyse_game
from chess_coach.engine import Analysis
from chess_coach.store import phase_of, save_explanation, save_game

PGN = '[White "Ann"]\n[Black "Bo"]\n[Result "1-0"]\n[Date "2025.03.04"]\n[ECO "C20"]\n\n1. e4 e5 2. Qh5 1-0'


class Flat:
    """Engine that always says +30 and recommends the same first legal move."""

    def analyse(self, board, depth=None, time=None, multipv=1):
        mv = next(iter(board.legal_moves)).uci()
        return [Analysis(cp=30, mate=None, best_move=mv, pv=[mv], depth=depth)]


def _analysis():
    return analyse_game(PGN, Flat(), depth=1)


def test_phase_rules():
    start = chess.STARTING_FEN
    assert phase_of(start, 5) == "opening"
    assert phase_of(start, 40) == "middlegame"
    assert phase_of("8/5k2/8/4P3/8/8/8/4K3 w - - 0 1", 60) == "endgame"
    # Two rooks in total is 10 points of non-pawn material: an endgame.
    assert phase_of("4k3/8/8/8/8/8/8/R3K2R w - - 0 1", 60) == "endgame"
    # Four rooks and a queen is 29 points: still a middlegame.
    assert phase_of("r3k2r/8/8/8/8/8/8/R2QK2R w - - 0 1", 60) == "middlegame"


def test_save_game_roundtrip_and_dedupe(pg):
    a = _analysis()
    gid = save_game(pg, PGN, a, engine_depth=1, engine_version="fake")
    assert gid is not None
    assert pg.execute("SELECT count(*) FROM moves WHERE game_id=%s", (gid,)).fetchone()[0] == 3
    assert pg.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 3
    row = pg.execute("SELECT white, result, eco, played_on::text FROM games").fetchone()
    assert row == ("Ann", "1-0", "C20", "2025-03-04")
    assert save_game(pg, PGN, a, engine_depth=1, engine_version="fake") is None  # duplicate
    assert pg.execute("SELECT count(*) FROM games").fetchone()[0] == 1


def test_facts_saved_only_for_key_moments_and_explanation_links(pg):
    a = _analysis()
    gid = save_game(pg, PGN, a, 1, "fake")
    n_key = len(a.key_moments)
    assert pg.execute("SELECT count(*) FROM facts").fetchone()[0] == n_key
    move_id = pg.execute("SELECT id FROM moves WHERE game_id=%s AND ply=1", (gid,)).fetchone()[0]
    eid = save_explanation(pg, move_id, "qwen", "text", False, 1)
    assert pg.execute("SELECT body FROM explanations WHERE id=%s", (eid,)).fetchone()[0] == "text"
