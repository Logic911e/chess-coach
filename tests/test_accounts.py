import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from chess_coach import accounts, sources
from chess_coach.api import create_app
from chess_coach.engine import Analysis

GAME = ('[Event "Live Chess"]\n[White "Me_1"]\n[Black "Rival"]\n[Result "1-0"]\n'
        '[Date "2026.11.02"]\n\n1. e4 {[%clk 0:03:00]} e5 2. Qh5 1-0\n')


class Flat:
    """Every position is level, so no move is a key moment and the import is fast."""
    version = "fake"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def analyse(self, board, depth=None, time=None, multipv=1):
        mv = next(iter(board.legal_moves)).uci()
        return [Analysis(cp=20, mate=None, best_move=mv, pv=[mv], depth=depth)]


def fake_get(url, accept):
    if url.endswith("/games/archives"):
        return json.dumps({"archives": ["https://api.chess.com/pub/player/me_1/games/2026/11",
                                        "https://api.chess.com/pub/player/me_1/games/2020/01"]})
    if url.endswith("/2026/11"):
        return json.dumps({"games": [
            {"pgn": GAME, "rules": "chess", "end_time": 1893000000},
            {"pgn": GAME, "rules": "chess960", "end_time": 1893000000}]})
    if "nobody" in url:
        raise sources.NoSuchUser(url)
    return "{}"


class NoClose:
    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, *a):
        return False


@pytest.fixture()
def http(pg):
    app = create_app(connect=lambda: NoClose(pg), fetch_get=fake_get,
                     sync_manager=accounts.SyncManager(lambda: NoClose(pg), Flat, fake_get, 1))
    return TestClient(app), app


def test_username_rules():
    assert sources.check_username("lichess", "Logic911e") == "Logic911e"
    for bad in ("a", "x" * 31, "a b", "a/../b", "a?x=1"):
        with pytest.raises(ValueError):
            sources.check_username("lichess", bad)
    with pytest.raises(ValueError):
        sources.check_username("myspace", "someone")


def test_months_ago_starts_on_the_first():
    now = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
    assert sources.months_ago(3, now) == datetime(2026, 8, 1, tzinfo=UTC)
    assert sources.months_ago(11, now) == datetime(2025, 12, 1, tzinfo=UTC)


def test_chesscom_skips_old_months_and_variants():
    out = sources.fetch("chesscom", "me_1", datetime(2026, 9, 1, tzinfo=UTC), fake_get)
    assert out == [GAME]


def test_link_sync_unlink_keep_games(http):
    client, app = http
    r = client.post("/api/accounts", json={"platform": "chesscom", "username": "Me_1", "months": 3})
    assert r.status_code == 201
    app.state.sync.wait()
    aid = r.json()["id"]
    [a] = client.get("/api/accounts").json()
    assert a["sync"]["state"] == "done" and a["games"] == 1 and a["last_synced_at"]
    assert client.get("/api/games").json()[0]["white"] == "Me_1"
    d = client.delete(f"/api/accounts/{aid}").json()
    assert d["games_deleted"] == 0
    assert client.get("/api/accounts").json() == []
    assert len(client.get("/api/games").json()) == 1  # kept


def test_unlink_can_delete_the_games(http):
    client, app = http
    aid = client.post("/api/accounts", json={"platform": "chesscom", "username": "Me_1"}).json()["id"]
    app.state.sync.wait()
    d = client.delete(f"/api/accounts/{aid}?delete_games=true").json()
    assert d["games_deleted"] == 1
    assert client.get("/api/games").json() == []


def test_link_errors(http):
    client, app = http
    assert client.post("/api/accounts", json={"platform": "lichess", "username": "nobody"}
                       ).status_code == 404
    assert client.post("/api/accounts", json={"platform": "lichess", "username": "a b"}
                       ).status_code == 422
    assert client.post("/api/accounts", json={"platform": "chesscom", "username": "Me_1"}
                       ).status_code == 201
    app.state.sync.wait()
    assert client.post("/api/accounts", json={"platform": "chesscom", "username": "me_1"}
                       ).status_code == 409
    assert client.delete("/api/accounts/9999").status_code == 404
    assert client.post("/api/accounts/9999/sync").status_code == 404
