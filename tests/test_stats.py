import pytest
from tests.test_api import Swingy

from chess_coach import openings
from chess_coach.analyser import analyse_game
from chess_coach.stats import build_stats, time_class
from chess_coach.store import save_game


def pgn(white, black, result, moves, tc="180+2", date="2025.03.04"):
    return (f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n[Date "{date}"]\n'
            f'[TimeControl "{tc}"]\n\n{moves} {result}')


GAMES = [
    pgn("Ann", "Bo", "1-0", "1. e4 e5 2. Nf3 Nc6 3. Bb5", "180+2"),       # Ann wins as white
    pgn("Bo", "Ann", "1-0", "1. d4 d5 2. c4 e6", "60"),                     # Ann loses as black
    pgn("Ann", "Cy", "1/2-1/2", "1. Nf3 d5 2. g3", "600"),                  # Ann draws as white
    pgn("Cy", "Dee", "1-0", "1. e4 c5 2. Nf3", "180"),                      # not Ann's
]


@pytest.fixture()
def seeded(pg):
    for text in GAMES:
        save_game(pg, text, analyse_game(text, Swingy(), depth=1), engine_depth=1, engine_version="f")
    return pg


def test_the_record_counts_only_the_players_games_whatever_the_case_of_the_name(seeded):
    s = build_stats(seeded, "ANN")
    o = s["overview"]
    assert (o["games"], o["wins"], o["draws"], o["losses"]) == (3, 1, 1, 1)
    assert o["moves"] == 7  # only Ann's own moves: 3 + 2 + 2
    assert 0 <= o["accuracy"] <= 100 and o["errors_per_100"] is not None


def test_a_player_with_no_games_has_no_stats(seeded):
    assert build_stats(seeded, "Nobody") is None


def test_pieces_and_phases_are_counted_from_the_players_own_moves(seeded):
    s = build_stats(seeded, "Ann")
    pieces = {p["key"]: p["moves"] for p in s["pieces"]}
    assert pieces == {"pawn": 4, "knight": 2, "bishop": 1}  # e4 d5 e6 g3; Nf3 Nf3; Bb5
    assert [p["key"] for p in s["phases"]] == ["opening"]
    assert all(p["small"] for p in s["pieces"])  # far too few moves to read anything from


def test_the_trend_has_one_entry_per_game_with_its_result_and_time_class(seeded):
    t = build_stats(seeded, "Ann")["trend"]
    assert [x["result"] for x in t] == ["win", "loss", "draw"]
    assert [x["time_class"] for x in t] == ["blitz", "bullet", "rapid"]
    assert [x["side"] for x in t] == ["white", "black", "white"]
    assert build_stats(seeded, "Ann")["time_classes"] == {"blitz": 1, "bullet": 1, "rapid": 1}


def test_openings_are_grouped_by_family_and_side_with_the_record(seeded):
    s = build_stats(seeded, "Ann")
    white = {o["name"]: o for o in s["openings"]["white"]}
    ruy = white["Ruy Lopez"]
    assert (ruy["games"], ruy["wins"], ruy["draws"], ruy["losses"], ruy["small"]) == (1, 1, 0, 0, True)
    assert len(s["openings"]["white"]) == 2          # the Ruy Lopez and the Zukertort-type game
    black = s["openings"]["black"]
    assert len(black) == 1 and black[0]["losses"] == 1
    assert black[0]["name"] == openings.classify(["d2d4", "d7d5", "c2c4", "e7e6"]).family
    assert s["unnamed_games"] == 0


def test_time_class_follows_the_lichess_rule_and_copes_with_odd_values():
    assert time_class("60") == "bullet" and time_class("179") == "bullet"
    assert time_class("180") == "blitz" and time_class("180+2") == "blitz"  # 3 minutes is blitz
    assert time_class("29") == "ultrabullet" and time_class("300") == "blitz"
    assert time_class("600") == "rapid" and time_class("1800+0") == "classical"
    assert time_class("1/86400") == "unknown" and time_class("-") == "unknown"
    assert time_class(None) == "unknown" and time_class("abc") == "unknown"


CLOCKED = ('[White "Ann"]\n[Black "Bo"]\n[Result "1-0"]\n[Date "2025.04.01"]\n[TimeControl "180+2"]\n\n'
           '1. e4 {[%clk 0:03:00]} e5 {[%clk 0:03:00]} 2. Nf3 {[%clk 0:02:59]} Nc6 {[%clk 0:02:50]} '
           '3. Bb5 {[%clk 0:00:10]} 1-0')


def test_clock_times_are_read_per_ply():
    from chess_coach.backfill import clocks
    assert clocks(CLOCKED) == [180000, 180000, 179000, 170000, 10000]
    assert clocks(GAMES[0]) == [None] * 5


def test_time_stats_split_moves_by_how_long_they_took(pg):
    save_game(pg, CLOCKED, analyse_game(CLOCKED, Swingy(), depth=1), engine_depth=1, engine_version="f")
    assert pg.execute("SELECT clock_ms FROM moves ORDER BY ply").fetchall() == [
        (180000,), (180000,), (179000,), (170000,), (10000,)]
    t = build_stats(pg, "Ann")["time"]
    # Ann's second move: 180 - 179 + 2 = 3 s. Her third: 179 - 10 + 2 = 171 s, with 10 s left.
    assert {b["key"]: b["moves"] for b in t["by_time"]} == {"instant": 0, "quick": 1, "long": 1}
    assert t["trouble"]["moves"] == 1 and t["not_trouble"]["moves"] == 1  # 10 s < a tenth of 180 s
    assert t["games"] == 1 and t["thresholds"]["long_s"] == 10


def test_no_clock_times_means_no_time_section(seeded):
    assert build_stats(seeded, "Ann")["time"] is None
