import json

import chess

from chess_coach import features as cf
from chess_coach.explainer import SYSTEM_PROMPT, boards_for_check, build_messages, explain

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
LINE = ["g7g6", "h5f3"]


def _facts():
    return cf.build_facts(QH5, "g8f6", "g7g6", 20, -700, best_line_uci=LINE)


class ScriptedClient:
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0)


def test_prompt_contains_facts_and_grounding_rules():
    facts = _facts()
    msgs = build_messages(facts)
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert json.loads(msgs[1]["content"].split("Facts:\n")[1].split("\n\nExplain")[0]) == facts
    assert "ONLY source of truth" in SYSTEM_PROMPT


def test_clean_reply_passes_first_time():
    client = ScriptedClient(["Nf6 was a blunder because it ignored the threat. g6 was best."])
    result = explain(_facts(), client, best_line_uci=LINE)
    assert not result.flagged and result.attempts == 1


def test_illegal_move_triggers_retry_then_passes():
    client = ScriptedClient(["Better was Nxe5, winning a pawn.", "g6 was the best move."])
    result = explain(_facts(), client, best_line_uci=LINE)
    assert not result.flagged and result.attempts == 2
    assert "Nxe5" in client.seen[1][-1]["content"]  # feedback names the offending move


def test_persistent_illegal_moves_are_flagged():
    client = ScriptedClient(["Rxh7 wins."] * 3)  # no white rook can reach h7
    result = explain(_facts(), client, best_line_uci=LINE)
    assert result.flagged and result.illegal_moves == ["Rxh7"]
    assert result.attempts == 3


def test_moves_deeper_in_engine_line_are_allowed():
    # Qf3 is only legal after ...g6, so it must be checked against the line positions.
    boards = boards_for_check(_facts(), LINE)
    assert any(b.fen() != chess.Board(QH5).fen() for b in boards)
    client = ScriptedClient(["After g6, White might play Qf3."])
    assert not explain(_facts(), client, best_line_uci=LINE).flagged


def test_false_piece_placement_triggers_retry_and_flag():
    bad = "Nf6 leaves two pawns hanging on e4 and h5."  # h5 holds White's queen
    good = "Nf6 ignored the threat to the pawn on f7. g6 was best."
    client = ScriptedClient([bad, good])
    result = explain(_facts(), client, best_line_uci=LINE)
    assert not result.flagged and result.attempts == 2
    assert "pawn on h5" in client.seen[1][-1]["content"]

    stuck = explain(_facts(), ScriptedClient([bad] * 3), best_line_uci=LINE)
    assert stuck.flagged and stuck.false_placements == ["pawn on h5"] and stuck.illegal_moves == []


def test_run_checked_retries_then_flags():
    from chess_coach.explainer import run_checked

    boards = boards_for_check(_facts(), LINE)
    client = ScriptedClient(["Rxh7 wins.", "Rxh7 still wins.", "Rxh7 really wins."])
    result = run_checked([{"role": "user", "content": "q"}], client, boards, max_retries=2)
    assert result.flagged and result.attempts == 3 and result.illegal_moves == ["Rxh7"]
    assert len(client.seen) == 3
    assert "not legal" in client.seen[1][-1]["content"]


def test_default_style_comes_from_the_environment(monkeypatch):
    import pytest

    from chess_coach.explainer import default_style

    monkeypatch.delenv("CHESS_COACH_STYLE", raising=False)
    assert default_style() == "fields"
    monkeypatch.setenv("CHESS_COACH_STYLE", "statements_rich")
    assert default_style() == "statements_rich"
    monkeypatch.setenv("CHESS_COACH_STYLE", "nonsense")
    with pytest.raises(ValueError):
        default_style()


WINQ = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"
WINQ_LINE = ["f3h4"]
FALSE_CLAIM = "By moving the pawn to d3, the white knight on f3 becomes undefended."


def _winq_facts():
    return cf.build_facts(WINQ, "d2d3", "f3h4", 700, -100, best_line_uci=WINQ_LINE)


def test_false_tactical_claim_triggers_a_retry_that_names_it():
    client = ScriptedClient([FALSE_CLAIM, "Nxh4 was the best move, winning the queen."])
    result = explain(_winq_facts(), client, best_line_uci=WINQ_LINE, style="statements")
    assert not result.flagged and result.attempts == 2 and result.false_claims == []
    feedback = client.seen[1][-1]["content"]
    assert "these claims are wrong: the white knight on f3 is defended" in feedback


def test_persistent_false_claim_is_flagged_with_the_claim_recorded():
    client = ScriptedClient([FALSE_CLAIM] * 3)
    result = explain(_winq_facts(), client, best_line_uci=WINQ_LINE, style="statements")
    assert result.flagged and result.attempts == 3
    assert result.false_claims == ["the white knight on f3 is defended"]


def test_true_tactical_claims_do_not_cost_a_retry():
    client = ScriptedClient(["The white knight on f3 attacks the black queen on h4."])
    result = explain(_winq_facts(), client, best_line_uci=WINQ_LINE, style="statements")
    assert not result.flagged and result.attempts == 1


def test_prompt_hash_changes_with_the_style_and_is_stable_otherwise():
    from chess_coach.explainer import prompt_hash

    facts = _facts()
    assert prompt_hash(facts, "statements") == prompt_hash(facts, "statements")
    assert prompt_hash(facts, "statements") != prompt_hash(facts, "statements_rich")
    assert prompt_hash(facts, "statements") != prompt_hash(facts, "statements_strict")
