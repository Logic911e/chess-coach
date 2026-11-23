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


def test_rich_statements_are_off_by_default_and_only_append():
    facts = _facts("g8f6")
    base = render_facts(facts)
    rich = render_facts(facts, rich=True)
    assert rich[: len(base)] == base and len(rich) > len(base)


def test_rich_statements_report_material_hanging_pieces_and_development():
    extra = render_facts(_facts("g8f6"), rich=True)[len(render_facts(_facts("g8f6"))):]
    text = "\n".join(extra)
    assert "material is level" in text
    assert "the black pawn on f7 is attacked more times than defended" in text
    assert "White still has 3 minor pieces (knights or bishops) on their starting squares." in text
    assert "2 white pieces attack squares next to the black king on e8." in text
    assert "The material balance does not change along the engine's best line." in text


def test_rich_material_statement_names_the_side_ahead():
    facts = cf.build_facts(
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 0 2", "g1f3", "g1f3", 0, 0,
        best_line_uci=["g1f3"],
    )
    text = "\n".join(render_facts(facts, rich=True))
    assert "Black is ahead by 9 points of material" in text  # White has no queen here
    facts = cf.build_facts(
        "rnb1kbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "d1h5", "g1f3", 0, -50,
        best_line_uci=["g1f3"],
    )
    assert "White is ahead by 9 points of material" in "\n".join(render_facts(facts, rich=True))


def test_strict_and_rich_styles_use_the_strict_prompt():
    from chess_coach.explainer import STATEMENTS_STRICT_SYSTEM_PROMPT, STATEMENTS_SYSTEM_PROMPT

    facts = _facts("g8f6")
    assert build_messages(facts, "statements")[0]["content"] == STATEMENTS_SYSTEM_PROMPT
    strict = build_messages(facts, "statements_strict")
    rich = build_messages(facts, "statements_rich")
    assert strict[0]["content"] == rich[0]["content"] == STATEMENTS_STRICT_SYSTEM_PROMPT
    assert len(rich[1]["content"]) > len(strict[1]["content"])
    assert strict[1]["content"] == build_messages(facts, "statements")[1]["content"]
