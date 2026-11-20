"""Read-only JSON API over the analysed games, plus on-demand explanations.

Run: uvicorn chess_coach.api:app   (needs Postgres, and Ollama for explanations)
The page that uses it lives in src/chess_coach/web/.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import chess
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chess_coach import db
from chess_coach.engine_service import EngineService
from chess_coach.explainer import explain
from chess_coach.llm import LLMError, OllamaClient
from chess_coach.store import save_explanation

WEB_DIR = Path(__file__).parent / "web"


def _best_san(fen: str, uci: str) -> str | None:
    board = chess.Board(fen)
    try:
        return board.san(chess.Move.from_uci(uci))
    except ValueError:
        return None


def _fen_after(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    board.push_uci(uci)
    return board.fen()


def line_to_uci(fen: str, line_san: str) -> list[str]:
    """Replay '3...g6 4. Qf3' from `fen`. The facts store the engine line as SAN only,
    but the guardrail wants UCI, so we convert; stop at the first token that fails."""
    board = chess.Board(fen)
    out: list[str] = []
    for token in re.sub(r"\d+\.+\s*", " ", line_san).split():
        try:
            move = board.parse_san(token)
        except ValueError:
            break
        out.append(move.uci())
        board.push(move)
    return out


def create_app(
    connect: Callable[[], psycopg.Connection] = db.connect,
    client_factory: Callable[[], object] = OllamaClient,
    engine_service: EngineService | None = None,
) -> FastAPI:
    engine = engine_service or EngineService()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.close()

    app = FastAPI(title="chess-coach", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/games")
    def list_games() -> list[dict]:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT g.id, g.white, g.black, g.result, g.opening, g.played_on::text,
                       count(m.id) AS moves,
                       count(f.move_id) AS key_moments,
                       count(*) FILTER (WHERE e.classification IN ('mistake', 'blunder'))
                           AS errors
                FROM games g
                LEFT JOIN moves m       ON m.game_id = g.id
                LEFT JOIN evaluations e ON e.move_id = m.id
                LEFT JOIN facts f       ON f.move_id = m.id
                GROUP BY g.id
                ORDER BY g.played_on DESC NULLS LAST, g.id DESC
                """
            ).fetchall()
        keys = ("id", "white", "black", "result", "opening", "played_on",
                "moves", "key_moments", "errors")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    @app.get("/api/games/{game_id}")
    def get_game(game_id: int) -> dict:
        with connect() as conn:
            g = conn.execute(
                "SELECT id, white, black, result, opening, eco, played_on::text"
                " FROM games WHERE id = %s", (game_id,),
            ).fetchone()
            if g is None:
                raise HTTPException(404, "no such game")
            rows = conn.execute(
                """
                SELECT m.id, m.ply, m.move_number, m.color, m.san, m.uci, m.fen_before, m.phase,
                       e.best_uci, e.cp_best, e.cp_played, e.expected_points_lost::float,
                       e.classification, f.reasons,
                       (SELECT x.body FROM explanations x WHERE x.move_id = m.id
                        ORDER BY x.id DESC LIMIT 1),
                       (SELECT x.flagged FROM explanations x WHERE x.move_id = m.id
                        ORDER BY x.id DESC LIMIT 1)
                FROM moves m
                JOIN evaluations e ON e.move_id = m.id
                LEFT JOIN facts f  ON f.move_id = m.id
                WHERE m.game_id = %s ORDER BY m.ply
                """,
                (game_id,),
            ).fetchall()
        moves = []
        for r in rows:
            moves.append({
                "id": r[0], "ply": r[1], "move_number": r[2], "color": r[3], "san": r[4],
                "uci": r[5], "fen_before": r[6], "fen_after": _fen_after(r[6], r[5]), "phase": r[7],
                "best_uci": r[8], "best_san": _best_san(r[6], r[8]),
                "cp_best": r[9], "cp_played": r[10], "expected_points_lost": r[11],
                "classification": r[12],
                "is_key_moment": r[13] is not None, "reasons": r[13] or [],
                "explanation": r[14], "explanation_flagged": r[15],
            })
        keys = ("id", "white", "black", "result", "opening", "eco", "played_on")
        return {**dict(zip(keys, g, strict=True)), "moves": moves}

    @app.post("/api/moves/{move_id}/explain")
    def explain_move(move_id: int, regenerate: bool = False) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT f.facts, m.fen_before FROM moves m JOIN facts f ON f.move_id = m.id"
                " WHERE m.id = %s", (move_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "explanations exist only for key moments")
            facts, fen = row
            if not regenerate:
                cached = conn.execute(
                    "SELECT body, flagged, model FROM explanations WHERE move_id = %s"
                    " ORDER BY id DESC LIMIT 1", (move_id,),
                ).fetchone()
                if cached:
                    return {"body": cached[0], "flagged": cached[1], "model": cached[2],
                            "cached": True}
            client = client_factory()
            line = line_to_uci(fen, facts.get("best_line", {}).get("line_san", ""))
            try:
                result = explain(facts, client, best_line_uci=line,  # type: ignore[arg-type]
                                 style="statements")
            except LLMError as exc:
                raise HTTPException(503, f"local model unavailable: {exc}") from exc
            model = getattr(client, "model", "unknown")
            save_explanation(conn, move_id, model, result.text, result.flagged, result.attempts)
            conn.commit()
            return {"body": result.text, "flagged": result.flagged, "model": model,
                    "cached": False}

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
