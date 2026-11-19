from pathlib import Path

from chess_coach.engine import Analysis
from chess_coach.import_games import ImportSummary, import_pgn, iter_games

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_games.pgn"


class Flat:
    def analyse(self, board, depth=None, time=None, multipv=1):
        mv = next(iter(board.legal_moves)).uci()
        return [Analysis(cp=30, mate=None, best_move=mv, pv=[mv], depth=depth)]


class Boom(Flat):
    def analyse(self, board, depth=None, time=None, multipv=1):
        raise RuntimeError("engine died")


def test_sample_file_parses_two_games():
    games = list(iter_games(SAMPLE))
    assert len(games) == 2
    assert games[0][0]["White"] == "Paul Morphy" and len(games[0][2]) == 33


def test_import_then_reimport_skips_duplicates(pg):
    first = import_pgn(pg, SAMPLE, Flat(), "fake", depth=1, log=lambda *_: None)
    assert first.imported == 2 and first.skipped_duplicate == 0
    assert pg.execute("SELECT count(*) FROM games").fetchone()[0] == 2
    second = import_pgn(pg, SAMPLE, Flat(), "fake", depth=1, log=lambda *_: None)
    assert second.imported == 0 and second.skipped_duplicate == 2
    assert pg.execute("SELECT count(*) FROM games").fetchone()[0] == 2


def test_a_failing_game_is_reported_and_rolled_back(pg):
    s = import_pgn(pg, SAMPLE, Boom(), "fake", depth=1, log=lambda *_: None)
    assert s.imported == 0 and len(s.failed) == 2 and "engine died" in s.failed[0]
    assert pg.execute("SELECT count(*) FROM games").fetchone()[0] == 0


def test_max_games_limit(pg):
    s = import_pgn(pg, SAMPLE, Flat(), "fake", depth=1, max_games=1, log=lambda *_: None)
    assert s.imported == 1 and isinstance(s, ImportSummary)
