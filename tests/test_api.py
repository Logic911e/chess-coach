import chess
import pytest
from fastapi.testclient import TestClient

from chess_coach.analyser import analyse_game
from chess_coach.api import create_app, line_to_uci, suggest_player
from chess_coach.engine import Analysis
from chess_coach.llm import LLMError
from chess_coach.store import save_game

PGN = '[White "Ann"]\n[Black "Bo"]\n[Result "1-0"]\n[Date "2025.03.04"]\n\n1. e4 e5 2. Qh5 1-0'


class Swingy:
    """White to move: +30. Black to move: +900. So every move looks like a blunder."""

    def analyse(self, board, depth=None, time=None, multipv=1):
        mv = next(iter(board.legal_moves)).uci()
        cp = 30 if board.turn == chess.WHITE else 900
        return [Analysis(cp=cp, mate=None, best_move=mv, pv=[mv], depth=depth)]


class NoClose:
    """Wrap the test connection so the API's `with connect()` does not close it."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *a):
        return False


class FakeClient:
    model = "fake-model"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def chat(self, messages):
        self.calls += 1
        if self.fail:
            raise LLMError("down")
        return "This move was a blunder."


@pytest.fixture()
def app_and_client(pg):
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="fake")
    pg.commit()
    client = FakeClient()
    app = create_app(connect=lambda: NoClose(pg), client_factory=lambda: client)
    return TestClient(app), client


def test_line_to_uci_replays_numbered_san():
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    assert line_to_uci(fen, "3...g6 4. Qf3") == ["g7g6", "h5f3"]
    assert line_to_uci(fen, "3...g6 4. Qz9") == ["g7g6"]  # stops at the first bad token


def test_list_and_get_game(app_and_client):
    http, _ = app_and_client
    games = http.get("/api/games").json()
    assert len(games) == 1 and games[0]["white"] == "Ann" and games[0]["moves"] == 3
    g = http.get(f"/api/games/{games[0]['id']}").json()
    assert [m["san"] for m in g["moves"]] == ["e4", "e5", "Qh5"]
    first = g["moves"][0]
    assert first["best_san"] and first["is_key_moment"] and first["classification"] == "blunder"
    assert http.get("/api/games/99999").status_code == 404


def test_explain_generates_then_caches(app_and_client):
    http, client = app_and_client
    gid = http.get("/api/games").json()[0]["id"]
    move_id = http.get(f"/api/games/{gid}").json()["moves"][0]["id"]
    r = http.post(f"/api/moves/{move_id}/explain").json()
    assert r["body"] == "This move was a blunder." and r["cached"] is False
    assert http.post(f"/api/moves/{move_id}/explain").json()["cached"] is True
    assert client.calls == 1
    assert http.post(f"/api/moves/{move_id}/explain?regenerate=true").json()["cached"] is False
    shown = http.get(f"/api/games/{gid}").json()["moves"][0]
    assert shown["explanation"] == "This move was a blunder."


def test_explain_unknown_move_and_model_down(pg):
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    http = TestClient(create_app(connect=lambda: NoClose(pg),
                                 client_factory=lambda: FakeClient(fail=True)))
    assert http.post("/api/moves/999999/explain").status_code == 404
    move_id = pg.execute("SELECT move_id FROM facts LIMIT 1").fetchone()[0]
    assert http.post(f"/api/moves/{move_id}/explain").status_code == 503


def _save(pg, pgn):
    save_game(pg, pgn, analyse_game(pgn, Swingy(), depth=1), engine_depth=1, engine_version="fake")
    pg.commit()


def test_move_flags(app_and_client, pg):
    http, _ = app_and_client
    gid = http.get("/api/games").json()[0]["id"]
    qh5 = http.get(f"/api/games/{gid}").json()["moves"][2]
    assert qh5["san"] == "Qh5" and qh5["check"] is False and qh5["capture"] is False
    _save(pg, '[White "Cy"]\n[Black "Di"]\n[Result "1-0"]\n\n1. e4 e5 2. Bc4 Nc6 3. Bxf7+ 1-0')
    gid2 = max(g["id"] for g in http.get("/api/games").json())
    bxf7 = http.get(f"/api/games/{gid2}").json()["moves"][4]
    assert bxf7["san"] == "Bxf7+" and bxf7["capture"] is True and bxf7["check"] is True


def test_suggest_player_majority_and_ties():
    assert suggest_player({"Ann": 3, "Bo": 2}, 5) == "Ann"
    assert suggest_player({"Ann": 2, "Bo": 2}, 4) is None
    assert suggest_player({}, 0) is None


def test_players_endpoint_counts_each_game_once(app_and_client, pg):
    http, _ = app_and_client
    _save(pg, '[White "Ann"]\n[Black "Ann"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 1-0')
    data = http.get("/api/players").json()
    assert data["players"] == [{"name": "Ann", "games": 2}, {"name": "Bo", "games": 1}]
    assert data["suggested"] == "Ann"
