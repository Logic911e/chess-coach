from tests.test_api import Swingy

from chess_coach import backfill, openings
from chess_coach.analyser import analyse_game
from chess_coach.store import save_game


def test_a_game_is_named_by_the_deepest_listed_position():
    ruy = openings.classify(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"])
    assert (ruy.eco, ruy.name) == ("C60", "Ruy Lopez")
    assert openings.classify(["e2e4"]).name == "King's Pawn Game"  # shallower than the Ruy Lopez


def test_a_transposition_gets_the_same_name_as_the_other_move_order():
    a = openings.classify(["g1f3", "d7d5", "d2d4"])
    b = openings.classify(["d2d4", "d7d5", "g1f3"])
    assert a == b and a is not None


def test_nothing_listed_or_no_moves_gives_none_and_a_bad_move_stops_the_walk():
    assert openings.classify([]) is None
    assert openings.classify(["e2e4", "e2e4"]).name == "King's Pawn Game"  # illegal 2nd move: keep what was found


def test_the_family_drops_the_variation():
    assert openings.family("Sicilian Defense: Closed") == "Sicilian Defense"
    assert openings.family("Ruy Lopez") == "Ruy Lopez"
    assert openings.classify(["g1f3", "d7d5", "d2d4"]).family == "Queen's Pawn Game"


def test_game_headers_are_read_from_the_pgn_tags():
    pgn = '[Event "x"]\n[WhiteElo "1850"]\n[BlackElo "abc"]\n[TimeControl "180+2"]\n\n1. e4 *'
    assert backfill.game_headers(pgn) == {"time_control": "180+2", "white_elo": 1850, "black_elo": None}
    assert backfill.game_headers('[Event "x"]\n\n1. e4 *') == {
        "time_control": None, "white_elo": None, "black_elo": None}


PGN = ('[White "Ann"]\n[Black "Bo"]\n[Result "1-0"]\n[Date "2025.03.04"]\n[WhiteElo "1500"]\n'
       '[TimeControl "180+2"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0')


def test_a_saved_game_is_named_and_keeps_its_time_control_and_rating(pg):
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    row = pg.execute("SELECT eco, opening, time_control, white_elo, black_elo FROM games").fetchone()
    assert row == ("C60", "Ruy Lopez", "180+2", 1500, None)


def test_backfill_names_old_games_without_touching_a_name_that_is_already_there(pg):
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.execute("UPDATE games SET opening = NULL, eco = NULL, time_control = NULL, white_elo = NULL")
    assert openings.backfill(pg) == 1
    assert pg.execute("SELECT eco, opening FROM games").fetchone() == ("C60", "Ruy Lopez")
    assert backfill.run(pg) == {"openings_named": 0, "headers_filled": 1, "games_with_clocks": 0}
    pg.execute("UPDATE games SET opening = 'My own name'")
    pg.execute("UPDATE games SET eco = NULL")
    openings.backfill(pg)
    assert pg.execute("SELECT eco, opening FROM games").fetchone() == ("C60", "My own name")
