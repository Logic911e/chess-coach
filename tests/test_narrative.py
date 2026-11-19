from chess_coach import features as cf
from chess_coach.explainer import build_messages
from chess_coach.narrative import render_facts

TRAP = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def _facts(played):
    return cf.build_facts(TRAP, played, "g7g6", 0, -900 if played == "g8f6" else 0,
                          best_line_uci=["g7g6", "h5f3"])


def test_blunder_statements_name_colour_and_square():
    text = "\n".join(render_facts(_facts("g8f6")))
    assert 'rated "blunder"' in text
    assert "the black knight on f6 attacks the white queen on h5" in text
    assert "black pawn on f7 was already under threat" in text
    assert "the white queen on h5 is attacked and undefended" in text
    assert "pinned by the white queen on h5" in text
    assert "The engine's best move is g6" in text


def test_best_move_played_says_so_and_has_no_alternative():
    text = "\n".join(render_facts(_facts("g7g6")))
    assert "also the engine's best move" in text
    assert "The engine's best move is" not in text


def test_statements_style_prompt_numbers_the_statements():
    msgs = build_messages(_facts("g8f6"), style="statements")
    assert msgs[1]["content"].startswith("Statements:\n1. ")
    assert "{" not in msgs[1]["content"]  # no raw JSON leaks through
