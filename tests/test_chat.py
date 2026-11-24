import chess
import pytest
from fastapi.testclient import TestClient
from tests.test_api import PGN, FakeClient, NoClose, Swingy, _Ctx, _first_move

from chess_coach import features as cf
from chess_coach.analyser import analyse_game
from chess_coach.api import create_app
from chess_coach.chat import answer_question, facts_for_move, named_moves
from chess_coach.engine import Analysis
from chess_coach.engine_service import EngineService
from chess_coach.store import save_game

START = chess.STARTING_FEN


class Scripted:
    model = "fake"

    def __init__(self, reply="Nf3 develops the knight."):
        self.reply, self.seen = reply, []

    def chat(self, messages):
        self.seen.append(messages)
        return self.reply


def _facts():
    return cf.build_facts(START, "e2e4", "e2e4", 20, 20, best_line_uci=["e2e4", "e7e5"])


def test_named_moves_keeps_only_legal():
    assert named_moves(START, "what if I play Nf3 or Qz9?") == ["g1f3"]
    assert named_moves(START, "how about e2e4?") == ["e2e4"]
    assert named_moves(START, "Qh5 or Nf3") == ["g1f3"]


def test_answer_not_flagged_for_user_named_legal_move():
    # Nf3 is not on the played/best line, but the user asked about it and it is legal
    client = Scripted("Nf3 develops the knight")
    r = answer_question(_facts(), ["e2e4", "e7e5"], START, "what about Nf3?", [], client)
    assert not r.flagged


def test_answer_flagged_when_it_names_a_move_not_legal_anywhere():
    client = Scripted("Rxh7 wins a pawn.")
    r = answer_question(_facts(), ["e2e4", "e7e5"], START, "what about Nf3?", [], client)
    assert r.flagged and r.illegal_moves == ["Rxh7"]


def test_history_is_capped_to_last_6_messages():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(10)
    ]
    client = Scripted("Fine.")
    answer_question(_facts(), [], START, "why?", history, client)
    sent = client.seen[0]
    contents = [m["content"] for m in sent]
    assert [c for c in contents if c.startswith("m")] == [f"m{i}" for i in range(4, 10)]
    assert sent[0]["role"] == "system" and sent[-1] == {"role": "user", "content": "why?"}


def test_facts_for_move_fetches_line_at_depth():
    seen = []

    class Eng:
        def analyse(self, board, depth, multipv=1):
            seen.append(depth)
            return [Analysis(cp=20, mate=None, best_move="e2e4", pv=["e2e4", "e7e5"], depth=depth)]

    facts, line = facts_for_move(START, "d2d4", "e2e4", 20, 10, 7, Eng())
    assert seen == [7] and line == ["e2e4", "e7e5"]
    assert facts["played"]["uci"] == "d2d4" and "best_line" in facts


@pytest.fixture()
def http(pg):
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    client = FakeClient()

    def build(engine=None, c=client):
        app = create_app(
            connect=lambda: NoClose(pg), client_factory=lambda: c,
            engine_service=EngineService(lambda: _Ctx(engine or Swingy())),
        )
        return TestClient(app)

    return build


def test_chat_endpoint_answers(http):
    h = http()
    m = _first_move(h)
    r = h.post(f"/api/moves/{m['id']}/chat", json={"question": "why?", "history": []})
    assert r.status_code == 200
    assert r.json() == {"body": "This move was a blunder.", "flagged": False}
    assert h.post("/api/moves/999999/chat", json={"question": "why?", "history": []}).status_code == 404


def test_empty_or_oversized_question_rejected_with_422(http):
    h = http()
    m = _first_move(h)
    for q in ("", "   ", "x" * 1001):
        r = h.post(f"/api/moves/{m['id']}/chat", json={"question": q, "history": []})
        assert r.status_code == 422
    ok = h.post(f"/api/moves/{m['id']}/chat", json={"question": "x" * 1000, "history": []})
    assert ok.status_code == 200
    bad = h.post(f"/api/moves/{m['id']}/chat",
                 json={"question": "hi", "history": [{"role": "system", "content": "x"}]})
    assert bad.status_code == 422


def test_chat_503_when_model_down(http):
    h = http(c=FakeClient(fail=True))
    m = _first_move(h)
    r = h.post(f"/api/moves/{m['id']}/chat", json={"question": "why?", "history": []})
    assert r.status_code == 503 and "model" in r.json()["detail"]


def test_chat_503_on_engine_failure_and_500_on_bugs(http, pg):
    class Dead:
        def analyse(self, board, depth=None, time=None, multipv=1):
            raise TimeoutError("engine died")

    class Buggy:
        def analyse(self, board, depth=None, time=None, multipv=1):
            return []

    h = http(Dead())
    m = _first_move(h)
    pg.execute("DELETE FROM facts WHERE move_id = %s", (m["id"],))  # make it a non-key move
    pg.commit()
    r = h.post(f"/api/moves/{m['id']}/chat", json={"question": "why?", "history": []})
    assert r.status_code == 503 and "engine" in r.json()["detail"]
    h2 = TestClient(http(Buggy()).app, raise_server_exceptions=False)
    r2 = h2.post(f"/api/moves/{m['id']}/chat", json={"question": "why?", "history": []})
    assert r2.status_code == 500 and "engine unavailable" not in r2.text


def test_history_bounds_rejected_with_422_and_limits_accepted(http):
    h = http()
    m = _first_move(h)
    url = f"/api/moves/{m['id']}/chat"

    def turns(n, size=10):
        return [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * size}
                for i in range(n)]

    assert h.post(url, json={"question": "hi", "history": turns(21)}).status_code == 422
    assert h.post(url, json={"question": "hi", "history": turns(1, 2001)}).status_code == 422
    ok = h.post(url, json={"question": "hi", "history": turns(20, 2000)})
    assert ok.status_code == 200


def _nd3_facts():
    fen = "5rk1/5pbp/r2qp1p1/p2pN3/4n3/1P2P3/PB3PPP/2RQ1RK1 w - - 4 17"
    return fen, cf.build_facts(fen, "e5d3", "d1e2", 5, -58, best_line_uci=["d1e2"])


def test_vet_answer_drops_fluff_and_invention_but_keeps_what_the_facts_support():
    from chess_coach.chat import vet_answer

    st = ["The move played is Nd3 (White's knight from e5 to d3).", "The engine's best move is Qe2."]
    text = ("Nd3 moves the knight from e5 to d3. It also keeps better control of the position. "
            "Bd5 would have won a pawn.")
    kept, dropped = vet_answer(text, st, "why not Nf4?")
    assert kept == "Nd3 moves the knight from e5 to d3."
    assert len(dropped) == 2 and "control" in dropped[0] and "d5" in dropped[1]


def test_a_move_the_player_named_may_be_repeated_in_the_answer():
    from chess_coach.chat import vet_answer

    kept, _ = vet_answer("The facts say nothing about Nf4.", ["The move played is Nd3."], "what about Nf4?")
    assert kept == "The facts say nothing about Nf4."


def test_an_answer_that_is_all_fluff_becomes_the_plain_cannot_answer_message():
    from chess_coach.chat import CANNOT_ANSWER

    fen, facts = _nd3_facts()
    client = Scripted("It maintains better control of the position and applies pressure.")
    out = answer_question(facts, ["d1e2"], fen, "why?", [], client)
    assert out.text == CANNOT_ANSWER and out.dropped


def test_the_chat_prompt_tells_the_model_to_agree_with_what_the_facts_confirm():
    from chess_coach.chat import CHAT_SYSTEM_PROMPT

    assert "agree and say so first" in CHAT_SYSTEM_PROMPT
    assert "do not say WHY" in CHAT_SYSTEM_PROMPT.replace("\n ", " ") or "WHY the engine" in CHAT_SYSTEM_PROMPT
    fen, facts = _nd3_facts()
    client = Scripted("You are right: Nd3 moves the knight from e5 to d3.")
    out = answer_question(facts, ["d1e2"], fen, "but the knight moved out of the way by going to d3", [], client)
    assert out.text == "You are right: Nd3 moves the knight from e5 to d3." and not out.dropped
