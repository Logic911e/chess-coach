"""The fields style: a verdict from code, a reason and a better from the model, each vetted alone."""

import json

from chess_coach import cited, fields
from chess_coach import features as cf
from chess_coach.explainer import explain

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
WINQ = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"
LINE = ["g7g6", "h5f3"]


class JsonClient:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def chat(self, messages, format=None):
        self.seen.append((messages, format))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def _facts(played="g8f6", cp_played=-700):
    return cf.build_facts(QH5, played, "g7g6", 20, cp_played, best_line_uci=LINE)


GOOD = {
    "reason": "The black pawn on f7 was already under threat, and Nf6 does not deal with that threat.",
    "better": "Black should have played g6, which attacks the white queen on h5.",
}


def by_key(result):
    return {f["key"]: f for f in result.fields}


def test_the_verdict_is_written_by_code_from_the_facts():
    lost = _facts()["expected_points_lost"]
    assert fields.verdict(_facts()) == f"Black's Nf6 is a blunder, losing {lost} expected points."
    assert fields.verdict(_facts("g7g6", 20)) == "Black's g6 is the engine's best move."
    ok = cf.build_facts(QH5, "g8f6", "g7g6", 20, 15, best_line_uci=LINE)
    assert "is rated" in fields.verdict(ok) and "blunder" not in fields.verdict(ok)


def test_parse_reads_two_fields_and_rejects_the_rest():
    assert fields.parse(json.dumps(GOOD)) == GOOD
    assert fields.parse("prose") is None and fields.parse('{"reason": "x"}') is None
    assert fields.parse('{"reason": "A (cites 3).", "better": ""}')["reason"] == "A."


def test_good_model_fields_are_kept_and_the_verdict_comes_from_code():
    client = JsonClient(GOOD)
    result = explain(_facts(), client, LINE, style="fields")
    f = by_key(result)
    assert [x["key"] for x in result.fields] == ["verdict", "reason", "better"]
    assert f["verdict"]["source"] == "code"
    assert f["reason"]["source"] == f["better"]["source"] == "model"
    assert not result.fallback and result.dropped == []
    assert result.text.startswith("Black's Nf6 is a blunder, losing")
    assert client.seen[0][1] == fields.SCHEMA


def test_a_bad_reason_is_replaced_alone_and_the_better_field_keeps_the_models_words():
    bad = {**GOOD, "reason": "Nf6 is a strong move that adds pressure on the centre."}
    result = explain(_facts(), JsonClient(bad), LINE, style="fields")
    f = by_key(result)
    assert f["reason"]["source"] == "facts" and "already under threat" in f["reason"]["text"]
    assert f["better"]["source"] == "model" and f["better"]["text"] == GOOD["better"]
    assert result.fallback and any("strong" in d for d in result.dropped)


def test_a_better_that_does_not_name_the_engines_move_is_replaced():
    vague = {**GOOD, "better": "A different move would have been wiser here."}
    result = explain(_facts(), JsonClient(vague), LINE, style="fields")
    f = by_key(result)
    assert f["better"]["source"] == "facts" and "should have played g6" in f["better"]["text"]
    assert f["reason"]["source"] == "model"


def test_a_move_that_was_the_engines_choice_has_no_better_field():
    facts = _facts("g7g6", 20)
    result = explain(facts, JsonClient({"reason": "It attacks the white queen on h5.",
                                        "better": "Something else."}), LINE, style="fields")
    assert [x["key"] for x in result.fields] == ["verdict", "reason"]
    assert any("engine's choice" in d for d in result.dropped)


def test_an_unreadable_reply_is_written_entirely_from_the_facts():
    result = explain(_facts(), JsonClient("sorry"), LINE, style="fields")
    f = by_key(result)
    assert f["reason"]["source"] == f["better"]["source"] == "facts"
    assert result.fallback and "expected format" in result.dropped[0]
    assert len(result.fields) == 3


def test_a_false_tactical_claim_in_the_reason_is_caught_and_replaced():
    facts = cf.build_facts(WINQ, "d2d3", "f3h4", 700, -100, best_line_uci=["f3h4"])
    reply = {"reason": "The white knight on f3 is undefended.",  # it is defended
             "better": "White should have played Nxh4, which captures the black queen on h4."}
    result = explain(facts, JsonClient(reply), ["f3h4"], style="fields")
    f = by_key(result)
    assert f["reason"]["source"] == "facts"
    assert "The white knight on f3 is undefended" not in result.text  # the false sentence is gone
    assert any("is defended" in d for d in result.dropped)
    assert f["better"]["source"] == "model"


def test_pawn_pushes_count_as_naming_the_engines_move():
    assert fields.mentions_best("Black should have played g6.", _facts())
    assert not fields.mentions_best("Black should have played g5.", _facts())
    assert cited.statements_for(_facts())  # the statements the fallbacks are built from
