import shutil

import chess
import pytest

from chess_coach.eval_cases import CASES
from chess_coach.evaluation import fen_only_messages, score, summarise


def test_case_ids_unique_and_moves_legal():
    assert len({c.id for c in CASES}) == len(CASES)
    for c in CASES:
        assert chess.Move.from_uci(c.played_uci) in chess.Board(c.fen).legal_moves, c.id


def test_fen_only_prompt_has_no_engine_facts():
    msgs = fen_only_messages(CASES[0].fen, "Nf6")
    joined = " ".join(m["content"] for m in msgs)
    assert CASES[0].fen in joined and "classification" not in joined and "best" not in joined.lower()


def test_score_flags_each_kind_of_false_claim():
    case = next(c for c in CASES if c.id == "qh5_g6")  # played best; calling it a blunder is false
    r = score(case, "x", 0, "Bad blunder: the knight on e4 hangs, so play Nxe5.", ["g7g6"])
    assert r.forbidden_hit and r.false_placements and r.illegal_moves and r.has_false_claim
    clean = score(case, "x", 0, "g6 stops Qxf7 and is the best move.", ["g7g6"])
    assert not clean.has_false_claim and clean.key_hit


def test_summarise_counts():
    case = CASES[1]
    rs = [score(case, "a", 0, "blunder", ["g7g6"]), score(case, "a", 1, "g6 is good", ["g7g6"])]
    s = summarise(rs)["a"]
    assert s["responses"] == 2 and s["with_false_claim"] == 1 and s["key_idea_mentioned"] == 1


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="Stockfish not installed")
def test_expected_labels_match_engine():
    from chess_coach.engine import Engine
    from chess_coach.evaluation import prepare

    with Engine() as eng:
        for c in CASES:
            prepare(c, eng, depth=14)  # raises if the engine disagrees with the label


def test_every_condition_builds_a_prompt():
    from chess_coach import features as cf
    from chess_coach.evaluation import ALL_CONDITIONS, condition_messages

    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    facts = cf.build_facts(fen, "g8f6", "g7g6", 0, -900, best_line_uci=["g7g6"])
    for cond in ALL_CONDITIONS:
        msgs = condition_messages(cond, facts, fen, "Nf6")
        assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"


def test_frozen_facts_load_and_manifest_survives_an_unreachable_model_server(tmp_path):
    import json

    from chess_coach.evaluation import load_frozen, manifest

    data = {"depth": 14, "engine_options": {"Threads": 1}, "stockfish": "Stockfish X",
            "cases": {"c": {"facts": {"a": 1}, "line": ["e2e4"], "san": "e4"}}}
    p = tmp_path / "facts.json"
    p.write_text(json.dumps(data))
    assert load_frozen(p) == data
    m = manifest("some-model", "http://127.0.0.1:9", data, {"seeds": [0]})
    assert m["stockfish"] == "Stockfish X" and m["ollama_version"] == "unknown"
    assert m["model_digest"] == "unknown" and len(m["facts_sha"]) == 16
    assert set(m["prompt_sha"]) >= {"statements", "statements_rich", "facts"}
    assert m["prompt_sha"]["statements_strict"] != m["prompt_sha"]["statements_rich"]


def test_best_and_excellent_count_as_the_same_label_band():
    from chess_coach.evaluation import _same_label

    assert _same_label("best", "excellent") and _same_label("excellent", "best")
    assert not _same_label("good", "excellent") and not _same_label("blunder", "best")
