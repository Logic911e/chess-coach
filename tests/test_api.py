import json

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


class Raising:
    def __init__(self):
        self.fail = True

    def analyse(self, board, depth=None, time=None, multipv=1):
        if self.fail:
            self.fail = False
            raise TimeoutError("engine died")
        return [Analysis(cp=0, mate=None, best_move="a2a3", pv=["a2a3"], depth=depth)]


def _first_move(http):
    gid = http.get("/api/games").json()[0]["id"]
    return http.get(f"/api/games/{gid}").json()["moves"][0]


def test_guess_endpoint_scores_and_404s(pg):
    from chess_coach.engine_service import EngineService
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    app = create_app(connect=lambda: NoClose(pg), engine_service=EngineService(lambda: _Ctx(Swingy())))
    http = TestClient(app)
    m = _first_move(http)
    r = http.post(f"/api/moves/{m['id']}/guess", json={"uci": m["best_uci"]}).json()
    assert r["legal"] and r["matched"] and r["classification"] == "best"
    assert r["best_san"] == m["best_san"] and r["san"] == m["best_san"]
    bad = http.post(f"/api/moves/{m['id']}/guess", json={"uci": "e2e5"}).json()
    assert bad["legal"] is False and bad["classification"] is None
    assert http.post("/api/moves/999999/guess", json={"uci": "e2e4"}).status_code == 404


def test_guess_endpoint_503_on_engine_error(pg):
    from chess_coach.engine_service import EngineService
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    engine = Raising()
    app = create_app(connect=lambda: NoClose(pg), engine_service=EngineService(lambda: _Ctx(engine)))
    http = TestClient(app)
    m = _first_move(http)
    other = "a2a3" if m["best_uci"] != "a2a3" else "b2b3"
    r = http.post(f"/api/moves/{m['id']}/guess", json={"uci": other})
    assert r.status_code == 503 and r.json()["detail"]
    assert http.post(f"/api/moves/{m['id']}/guess", json={"uci": other}).status_code == 200


class _Ctx:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self.engine

    def __exit__(self, *a):
        return False


def test_guess_endpoint_does_not_relabel_programming_errors(pg):
    from chess_coach.engine_service import EngineService

    class Buggy:
        def analyse(self, board, depth=None, time=None, multipv=1):
            return []  # IndexError inside scoring, not an engine failure

    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    app = create_app(connect=lambda: NoClose(pg), engine_service=EngineService(lambda: _Ctx(Buggy())))
    http = TestClient(app, raise_server_exceptions=False)
    m = _first_move(http)
    other = "a2a3" if m["best_uci"] != "a2a3" else "b2b3"
    r = http.post(f"/api/moves/{m['id']}/guess", json={"uci": other})
    assert r.status_code == 500
    assert "engine unavailable" not in r.text


def _elements(html):
    from html.parser import HTMLParser

    found = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.append((tag, dict(attrs)))

    P().feed(html)
    return found


def test_index_has_live_region_and_move_list_container(app_and_client):
    http, _ = app_and_client
    els = _elements(http.get("/").text)
    by_id = {a["id"]: (tag, a) for tag, a in els if "id" in a}
    assert by_id["moveList"][0] == "ul"
    assert "chatAnnounce" in by_id and by_id["chatAnnounce"][1]["aria-live"] == "polite"
    # the chat log itself is not live (only assistant answers are announced), and the caption
    # section is not live (the live region is scoped to the move name and label)
    assert by_id["chatLog"][1]["aria-live"] == "off"
    assert "aria-live" not in by_id["caption"][1]
    live = [a for _, a in els if a.get("class") == "cap-live"]
    assert len(live) == 1 and live[0]["aria-live"] == "polite"


def test_index_has_analysis_bar_tabs_and_toggle_ids(app_and_client):
    http, _ = app_and_client
    els = _elements(http.get("/").text)
    by_id = {a["id"]: (tag, a) for tag, a in els if "id" in a}
    for i in ("evalBar", "tabCoach", "tabAnalysis", "coachPanel", "analysisPanel", "analysisToggle",
              "exploreBanner", "exploreAnnounce"):
        assert i in by_id, i
    assert by_id["evalBar"][1]["role"] == "img"
    for i in ("tabCoach", "tabAnalysis", "analysisToggle"):
        assert by_id[i][0] == "button" and "aria-pressed" in by_id[i][1], i
    assert "role" not in by_id["tabCoach"][1] and "role" not in by_id["tabAnalysis"][1]
    # one persistent polite live region announces exploring; the banner is a labelled region, not live
    assert by_id["exploreAnnounce"][1]["aria-live"] == "polite"
    assert "aria-live" not in by_id["exploreBanner"][1] and "role" in by_id["exploreBanner"][1]
    assert by_id["exploreBanner"][1]["role"] != "status"
    # the existing caption content stays inside the coach panel
    assert "moveName" in by_id and "guessForm" in by_id


def test_guess_endpoint_played_move_uses_stored_score_and_long_uci_is_422(pg):
    from chess_coach.engine_service import EngineService

    class Counting:
        calls = 0

        def analyse(self, board, depth=None, time=None, multipv=1):
            Counting.calls += 1
            return [Analysis(cp=0, mate=None, best_move="a2a3", pv=["a2a3"], depth=depth)]

    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    app = create_app(connect=lambda: NoClose(pg),
                     engine_service=EngineService(lambda: _Ctx(Counting())))
    http = TestClient(app)
    gid = http.get("/api/games").json()[0]["id"]
    moves = http.get(f"/api/games/{gid}").json()["moves"]
    m = next((x for x in moves if x["uci"] != x["best_uci"]), moves[0])
    r = http.post(f"/api/moves/{m['id']}/guess", json={"uci": m["uci"]}).json()
    assert r["legal"] and r["classification"] == m["classification"]
    assert Counting.calls == 0
    assert http.post(f"/api/moves/{m['id']}/guess", json={"uci": "e2e4qq"}).status_code == 422


class _SvcAnalysis:
    """Stands in for EngineService on /api/analysis."""

    version = "Stockfish test"

    def __init__(self, exc=None):
        self.exc, self.calls = exc, []

    def analyse_background(self, board, depth, multipv=1, time=None, max_wait=2.0):
        self.calls.append((board.fen(), depth, multipv, time))
        if self.exc:
            raise self.exc
        out = []
        for i, mv in enumerate(list(board.legal_moves)[:multipv]):
            out.append(Analysis(cp=25 - i, mate=None, best_move=mv.uci(), pv=[mv.uci()], depth=9))
        return out

    def close(self):
        pass


def _analysis_client(svc, **kw):
    return TestClient(create_app(engine_service=svc), **kw)


def test_analysis_endpoint_shape():
    svc = _SvcAnalysis()
    http = _analysis_client(svc)
    black = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    r = http.post("/api/analysis", json={"fen": black, "lines": 2})
    assert r.status_code == 200
    j = r.json()
    assert j["game_over"] is False and j["depth"] == 9 and j["version"] == "Stockfish test"
    assert len(j["lines"]) == 2
    assert j["lines"][0]["score"] == {"cp": -25, "mate": None}  # White's perspective
    mv = j["lines"][0]["moves"][0]
    assert set(mv) == {"san", "uci", "fen", "capture", "check"}
    assert svc.calls[0][1:] == (16, 2, 3.0)
    over = http.post("/api/analysis", json={"fen": "R5k1/5ppp/8/8/8/8/8/4K3 b - - 0 1"}).json()
    assert over == {"game_over": True, "result": "checkmate"}
    assert len(svc.calls) == 1


def test_analysis_rejects_bad_fen_depth_lines_and_long_fen_with_422():
    http = _analysis_client(_SvcAnalysis())
    start = chess.STARTING_FEN
    bad = [
        {"fen": "nonsense"},
        {"fen": ""},
        {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"},  # no kings
        {"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 " + "x" * 100},
        {"fen": start, "depth": 0},
        {"fen": start, "depth": 21},
        {"fen": start, "lines": 0},
        {"fen": start, "lines": 6},
    ]
    for body in bad:
        assert http.post("/api/analysis", json=body).status_code == 422, body
    assert http.post("/api/analysis", json={"fen": start, "depth": 20, "lines": 5}).status_code == 200


def test_analysis_busy_returns_503_engine_busy():
    from chess_coach.engine_service import EngineBusy
    http = _analysis_client(_SvcAnalysis(EngineBusy("busy")))
    r = http.post("/api/analysis", json={"fen": chess.STARTING_FEN})
    assert r.status_code == 503 and r.json()["detail"] == "engine busy"


def test_analysis_engine_failure_returns_503():
    http = _analysis_client(_SvcAnalysis(TimeoutError("engine hung")))
    r = http.post("/api/analysis", json={"fen": chess.STARTING_FEN})
    assert r.status_code == 503 and "engine unavailable" in r.json()["detail"]


def test_analysis_programming_error_is_500_and_logged(caplog):
    http = _analysis_client(_SvcAnalysis(KeyError("bug")), raise_server_exceptions=False)
    r = http.post("/api/analysis", json={"fen": chess.STARTING_FEN})
    assert r.status_code == 500 and "engine unavailable" not in r.text
    assert any(rec.exc_info for rec in caplog.records)


def test_analysis_second_identical_request_is_a_cache_hit():
    svc = _SvcAnalysis()
    http = _analysis_client(svc)
    body = {"fen": chess.STARTING_FEN, "depth": 12, "lines": 2}
    a = http.post("/api/analysis", json=body).json()
    b = http.post("/api/analysis", json=body).json()
    assert a == b and len(svc.calls) == 1
    http.post("/api/analysis", json={**body, "depth": 13})
    assert len(svc.calls) == 2


class _LazyVersionSvc(_SvcAnalysis):
    """version is None until the first search has started the engine."""

    def __init__(self, empty=False):
        super().__init__()
        self._started, self.empty = False, empty

    @property
    def version(self):
        return "Stockfish lazy" if self._started else None

    def analyse_background(self, board, depth, multipv=1, time=None, max_wait=2.0):
        if self.empty:
            self.calls.append((board.fen(), depth, multipv, time))
            out = []
        else:
            out = super().analyse_background(board, depth, multipv, time)
        self._started = True
        return out


def test_analysis_version_is_read_after_the_search_and_cached():
    svc = _LazyVersionSvc()
    http = _analysis_client(svc)
    body = {"fen": chess.STARTING_FEN}
    assert http.post("/api/analysis", json=body).json()["version"] == "Stockfish lazy"
    assert http.post("/api/analysis", json=body).json()["version"] == "Stockfish lazy"
    assert len(svc.calls) == 1


def test_analysis_empty_lines_result_is_not_cached():
    svc = _LazyVersionSvc(empty=True)
    http = _analysis_client(svc)
    body = {"fen": chess.STARTING_FEN}
    assert http.post("/api/analysis", json=body).json()["lines"] == []
    http.post("/api/analysis", json=body)
    assert len(svc.calls) == 2


def _first_move_id(http):
    gid = http.get("/api/games").json()[0]["id"]
    return gid, http.get(f"/api/games/{gid}").json()["moves"][0]["id"]


def test_changing_the_style_is_a_cache_miss_and_old_text_is_marked_not_current(
    app_and_client, monkeypatch
):
    http, client = app_and_client
    monkeypatch.setenv("CHESS_COACH_STYLE", "statements")
    gid, move_id = _first_move_id(http)
    first = http.post(f"/api/moves/{move_id}/explain").json()
    assert first["cached"] is False and first["current"] is True and "checked_claims" in first
    assert http.post(f"/api/moves/{move_id}/explain").json()["cached"] is True
    assert http.get(f"/api/games/{gid}").json()["moves"][0]["explanation_current"] is True

    monkeypatch.setenv("CHESS_COACH_STYLE", "statements_rich")  # a different prompt
    assert http.get(f"/api/games/{gid}").json()["moves"][0]["explanation_current"] is False
    again = http.post(f"/api/moves/{move_id}/explain").json()
    assert again["cached"] is False and client.calls == 2  # regenerated, not served stale
    assert http.get(f"/api/games/{gid}").json()["moves"][0]["explanation_current"] is True


def test_a_legacy_row_is_shown_but_never_treated_as_current(pg):
    from chess_coach.store import save_explanation

    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    client = FakeClient()
    http = TestClient(create_app(connect=lambda: NoClose(pg), client_factory=lambda: client))
    gid, move_id = _first_move_id(http)
    save_explanation(pg, move_id, "fake-model", "old text", False, 1)  # no provenance: 'legacy'
    pg.commit()
    shown = http.get(f"/api/games/{gid}").json()["moves"][0]
    assert shown["explanation"] == "old text" and shown["explanation_current"] is False
    fresh = http.post(f"/api/moves/{move_id}/explain").json()
    assert fresh["cached"] is False and fresh["body"] == "This move was a blunder."
    assert client.calls == 1


class FieldsClient:
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, format=None):
        self.calls += 1
        return json.dumps({"reason": "It was a poor choice.", "better": "Something else was better."})


def test_a_fields_explanation_is_saved_cached_and_shown_with_its_parts(pg, monkeypatch):
    monkeypatch.setenv("CHESS_COACH_STYLE", "fields")
    save_game(pg, PGN, analyse_game(PGN, Swingy(), depth=1), engine_depth=1, engine_version="f")
    pg.commit()
    client = FieldsClient()
    http = TestClient(create_app(connect=lambda: NoClose(pg), client_factory=lambda: client))
    gid, move_id = _first_move_id(http)
    first = http.post(f"/api/moves/{move_id}/explain").json()
    keys = [f["key"] for f in first["fields"]]
    assert keys[0] == "verdict" and first["fields"][0]["source"] == "code"
    assert first["body"] == " ".join(f["text"] for f in first["fields"]) and first["cached"] is False
    again = http.post(f"/api/moves/{move_id}/explain").json()
    assert again["cached"] is True and again["fields"] == first["fields"] and client.calls == 1
    shown = http.get(f"/api/games/{gid}").json()["moves"][0]
    assert shown["explanation_fields"] == first["fields"] and shown["explanation_current"] is True


def test_the_stats_endpoint_returns_a_players_stats_and_rejects_bad_requests(app_and_client):
    http, _ = app_and_client
    ok = http.get("/api/stats", params={"player": "ann"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["player"] == "ann" and body["overview"]["games"] == 1
    assert set(body) >= {"trend", "phases", "pieces", "openings", "notes", "time_classes"}
    assert http.get("/api/stats", params={"player": "Nobody"}).status_code == 404
    assert http.get("/api/stats", params={"player": "  "}).status_code == 422
    assert http.get("/api/stats").status_code == 422
    assert http.get("/api/stats", params={"player": "x" * 101}).status_code == 422


def test_the_stats_page_and_its_files_are_served(app_and_client):
    http, _ = app_and_client
    page = http.get("/stats")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "/static/js/stats.js" in page.text
    for path in ("/static/js/stats.js", "/static/js/stats-view.js", "/static/css/stats.css"):
        assert http.get(path).status_code == 200, path
