"""Cited sentences: what is kept, what is dropped and why."""

import json

from chess_coach import cited
from chess_coach import features as cf
from chess_coach.explainer import default_style, explain, prompt_hash

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
WINQ = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"


class JsonClient:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def chat(self, messages, format=None):
        self.seen.append((messages, format))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def _facts():
    return cf.build_facts(QH5, "g8f6", "g7g6", 20, -700, best_line_uci=["g7g6", "h5f3"])


def _reply(*pairs):
    return {"sentences": [{"text": t, "cites": c} for t, c in pairs]}


def test_parse_reads_the_expected_shape_and_rejects_the_rest():
    ok = cited.parse(json.dumps(_reply(("A sentence.", [1, 2]))))
    assert ok == [{"text": "A sentence.", "cites": [1, 2]}]
    assert cited.parse("not json") is None
    assert cited.parse('{"other": 1}') is None
    assert cited.parse('{"sentences": [{"text": "x"}]}') == [{"text": "x", "cites": []}]


def test_each_reason_for_dropping_a_sentence():
    st = ["The black knight on f6 attacks the white queen on h5.", "Material is level.",
          "The engine's best move is g6."]

    def g(text, cites):
        return cited.ground({"text": text, "cites": cites}, st)

    assert g("The knight on f6 attacks the queen on h5.", [1]) is None
    assert g("Anything.", []) == "cites nothing"
    assert "does not exist" in g("Anything.", [9])
    assert "e4" in g("The knight on f6 attacks the pawn on e4.", [1])
    assert "Qxf7" in g("Black must stop Qxf7.", [1])
    assert "9" in g("This costs 9 points.", [2])
    assert "pressure" in g("It adds pressure.", [1])


def test_a_strategy_word_is_allowed_when_the_cited_statement_uses_it():
    st = ["White has more space than Black."]
    assert cited.ground({"text": "White has more space.", "cites": [1]}, st) is None


def test_two_good_sentences_are_kept_and_nothing_else_is_added():
    facts = _facts()
    st = cited.statements_for(facts)
    i = next(n for n, s in enumerate(st, 1) if "rated" in s)
    j = next(n for n, s in enumerate(st, 1) if "should have played" in s)
    client = JsonClient(_reply(("The move was a blunder.", [i]),
                               ("Black should have played g6 instead of Nf6", [j])))
    result = explain(facts, client, ["g7g6", "h5f3"], style="cited")
    assert not result.fallback and result.dropped == []
    assert result.text == "The move was a blunder. Black should have played g6 instead of Nf6."
    messages, schema = client.seen[0]
    assert schema == cited.SCHEMA and messages[1]["content"].startswith("Statements:\n1. ")


def test_unsupported_sentences_are_dropped_and_too_little_falls_back_to_the_statements():
    facts = _facts()
    client = JsonClient(_reply(
        ("The move was a blunder.", [1]),
        ("It also controls the centre.", [1]),  # vague word not in statement 1
        ("It loses 9 points.", []),             # cites nothing
    ))
    result = explain(facts, client, ["g7g6", "h5f3"], style="cited")
    assert result.fallback and result.text.startswith('The move is rated "blunder"')
    assert "(0 = no loss" not in result.text and "to move." not in result.text.split(".")[0]
    assert len(result.dropped) == 2 and "centre" in result.dropped[0]


def test_an_unreadable_reply_falls_back_without_a_retry():
    client = JsonClient("sorry, here is some prose")
    result = explain(_facts(), client, ["g7g6"], style="cited")
    assert result.fallback and "expected format" in result.dropped[0]
    assert len(client.seen) == 1


def test_a_false_tactical_claim_that_cites_a_real_statement_is_still_dropped():
    facts = cf.build_facts(WINQ, "d2d3", "f3h4", 700, -100, best_line_uci=["f3h4"])
    st = cited.statements_for(facts)
    i = next(n for n, s in enumerate(st, 1) if "f3" in s)
    client = JsonClient(_reply(
        ("The white knight on f3 is undefended.", [i]),  # it is defended by the queen and a pawn
        ("The move was a blunder.", [1]),
        ("The engine's best move is Nxh4.", [i]),
    ))
    result = explain(facts, client, ["f3h4"], style="cited")
    assert "The white knight on f3 is undefended" not in result.text
    assert any("is defended" in d for d in result.dropped)
    assert "Nxh4" in result.text


def test_the_cited_style_is_selectable_and_has_its_own_prompt_fingerprint(monkeypatch):
    monkeypatch.setenv("CHESS_COACH_STYLE", "cited")
    assert default_style() == "cited"
    facts = _facts()
    assert prompt_hash(facts, "cited") != prompt_hash(facts, "statements_rich")


def test_statement_numbers_written_into_the_prose_are_removed_before_checking():
    cases = {
        "This move attacks the queen on h5 (cites: 3).": "This move attacks the queen on h5.",
        "The move was a blunder, as stated in statement 1.": "The move was a blunder.",
        "Ra8# is checkmate (cited in 4, 7).": "Ra8# is checkmate.",
        "It attacks the pawn, as noted in 3 and 5.": "It attacks the pawn.",
    }
    for raw, clean in cases.items():
        assert cited.strip_citations(raw) == clean
    assert cited.strip_citations("White has 3 minor pieces.") == "White has 3 minor pieces."


def test_a_square_in_another_statement_is_accepted_but_the_cites_are_marked_loose():
    st = ["The move is rated blunder.", "The move played is d3 (a pawn from d2 to d3)."]
    sentence = {"text": "The move d3 is a blunder.", "cites": [1]}
    assert cited.ground(sentence, st) is None  # d3 is in the statements, just not the cited one
    assert cited.supported_by_cites(sentence, st) is False
    assert cited.supported_by_cites({"text": "The move d3 is a blunder.", "cites": [1, 2]}, st)
    assert cited.ground({"text": "The move e5 is a blunder.", "cites": [1]}, st)  # e5 nowhere


def test_praise_that_the_facts_do_not_contain_is_dropped():
    st = ["The move is rated best.", "It gives check."]
    for text in ("It is a strong defensive move.", "It is highly effective.", "A powerful reply."):
        assert cited.ground({"text": text, "cites": [1]}, st) is not None
    assert cited.ground({"text": "The move is rated best and gives check.", "cites": [1, 2]}, st) is None


def test_the_fallback_skips_a_long_wall_of_moves():
    st = ["Black to move.", "The move played is g6.",
          "The engine's best line is " + " ".join(f"{i}. Nf3 Nf6" for i in range(1, 12)) + "."]
    assert "best line" not in cited.template(st)
    short = [*st[:2], "The engine's best line is 1. e4 e5."]
    assert "best line" in cited.template(short)


def test_a_paragraph_in_one_entry_is_split_into_sentences_that_share_its_cites():
    raw = json.dumps({"sentences": [{
        "text": "The move was a blunder (cites 1). It lost 0.5 points (cites 1). "
                "The line is 3...g6 4. Qf3 Nf6.",
        "cites": [1, 2]}]})
    got = cited.parse(raw)
    assert [s["text"] for s in got] == [
        "The move was a blunder.", "It lost 0.5 points.", "The line is 3...g6 4. Qf3 Nf6."]
    assert all(s["cites"] == [1, 2] for s in got)  # the move number "4." did not end a sentence


def test_one_bad_sentence_in_a_paragraph_does_not_sink_the_good_ones():
    facts = _facts()
    st = cited.statements_for(facts)
    blob = {"sentences": [{"text": "The move was rated a blunder. It also gives strong pressure. "
                                    "Black should have played g6 instead of Nf6.",
                           "cites": [1, 2]}]}
    result = explain(facts, JsonClient(blob), ["g7g6", "h5f3"], style="cited")
    assert not result.fallback and len(result.dropped) == 1 and "strong" in result.dropped[0]
    assert result.text.startswith("The move was rated a blunder.")
    assert "pressure" not in result.text and st


def test_the_fallback_explains_why_and_not_only_the_rating():
    facts = _facts()
    text = cited.template(cited.statements_for(facts))
    assert text.startswith('The move is rated "blunder"')
    assert "already under threat" in text          # the reason Nf6 was bad
    assert "should have played g6" in text          # what was better
    assert "(0 = no loss" not in text
    assert len(text.split(". ")) <= 10              # a short answer, not every statement


def test_a_sentence_that_ends_in_a_square_is_split_from_the_next_but_a_move_number_is_not():
    got = cited.split_sentences("Nd3 moves the knight from e5 to d3. It is rated best. The line is 3...g6 4. Qf3 Nf6.")
    assert got == ["Nd3 moves the knight from e5 to d3.", "It is rated best.",
                   "The line is 3...g6 4. Qf3 Nf6."]
    assert cited.split_sentences("Black plays 10. Bxe6 fxe6.") == ["Black plays 10. Bxe6 fxe6."]


def test_vague_judgement_of_a_position_is_dropped_unless_a_statement_says_it():
    st = ["The move played is Nd3.", "The engine's best move is Qe2."]
    for text in ("Nd3 does not maximize White's potential.",
                 "It does not compensate for the overall worse position.",
                 "Qe2 gives White a stronger setup."):
        assert cited.ground({"text": text}, st, need_cites=False) is not None
    assert cited.ground({"text": "The engine preferred Qe2."}, st, need_cites=False) is None
