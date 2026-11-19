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
