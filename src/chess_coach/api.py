"""Read-only JSON API over the analysed games, plus on-demand explanations.

Run: uvicorn chess_coach.api:app   (needs Postgres, and Ollama for explanations)
The page that uses it lives in src/chess_coach/web/.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import chess
import chess.engine
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from chess_coach import db
from chess_coach.analysis import ANALYSIS_TIME_CAP, AnalysisCache, analyse_fen
from chess_coach.chat import answer_question, facts_for_move
from chess_coach.engine import EngineNotFoundError
from chess_coach.engine_service import EngineBusy, EngineService
from chess_coach.explainer import default_style, explain, prompt_hash
from chess_coach.factcheck import CHECKER_VERSION
from chess_coach.guess import score_guess
from chess_coach.llm import LLMError, OllamaClient
from chess_coach.stats import build_stats
from chess_coach.store import save_explanation

WEB_DIR = Path(__file__).parent / "web"


log = logging.getLogger(__name__)

# What a dead, missing or hung Stockfish raises (the cases EngineService restarts on).
ENGINE_FAILURES = (
    chess.engine.EngineError, chess.engine.EngineTerminatedError, EngineNotFoundError,
    OSError, TimeoutError,
)


class GuessBody(BaseModel):
    uci: str = Field(max_length=5)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatBody(BaseModel):
    question: str = Field(max_length=1000)
    history: list[ChatTurn] = Field(default=[], max_length=20)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class AnalysisBody(BaseModel):
    fen: str = Field(max_length=100)
    depth: int = Field(default=16, ge=1, le=20)
    lines: int = Field(default=3, ge=1, le=5)

    @field_validator("fen")
    @classmethod
    def _legal_fen(cls, v: str) -> str:
        try:
            board = chess.Board(v)
        except ValueError as exc:
            raise ValueError("not a valid FEN") from exc
        if not board.is_valid():
            raise ValueError("not a legal position")
        return v


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


def _move_flags(fen: str, uci: str) -> tuple[bool, bool]:
    """(capture, check) for `uci` played from `fen`; check includes mate."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    capture = board.is_capture(move)
    board.push(move)
    return capture, board.is_check()


def suggest_player(counts: dict[str, int], total_games: int) -> str | None:
    """The name appearing in more than half of the games, else None."""
    for name, n in counts.items():
        if total_games and n * 2 > total_games:
            return name
    return None


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

    @app.get("/api/players")
    def list_players() -> dict:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT name, count(DISTINCT id) AS games
                FROM (SELECT id, white AS name FROM games
                      UNION ALL SELECT id, black FROM games) p
                WHERE name IS NOT NULL AND name <> ''
                GROUP BY name ORDER BY games DESC, name
                """
            ).fetchall()
            total = conn.execute("SELECT count(*) FROM games").fetchone()[0]
        counts = {name: n for name, n in rows}
        return {
            "players": [{"name": name, "games": n} for name, n in rows],
            "suggested": suggest_player(counts, total),
        }

    @app.get("/api/stats")
    def player_stats(player: str) -> dict:
        name = player.strip()
        if not name or len(name) > 100:
            raise HTTPException(422, "player must be 1 to 100 characters")
        with connect() as conn:
            data = build_stats(conn, name)
        if data is None:
            raise HTTPException(404, "no stored games for that player")
        return data

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
                       x.body, x.flagged, x.model, x.prompt_hash, x.checker_version,
                       x.checked_claims, f.facts, x.fields
                FROM moves m
                JOIN evaluations e ON e.move_id = m.id
                LEFT JOIN facts f  ON f.move_id = m.id
                LEFT JOIN LATERAL (
                    SELECT body, flagged, model, prompt_hash, checker_version, checked_claims, fields
                    FROM explanations WHERE move_id = m.id ORDER BY id DESC LIMIT 1
                ) x ON true
                WHERE m.game_id = %s ORDER BY m.ply
                """,
                (game_id,),
            ).fetchall()
        style = default_style()
        model_now = getattr(client_factory(), "model", "unknown")
        moves = []
        for r in rows:
            # "current" = written by the model, prompt and checker that would write it today
            current = bool(
                r[14] is not None and r[20] is not None and r[16] == model_now
                and r[17] == prompt_hash(r[20], style) and r[18] == CHECKER_VERSION
            )
            capture, check = _move_flags(r[6], r[5])
            moves.append({
                "capture": capture, "check": check,
                "id": r[0], "ply": r[1], "move_number": r[2], "color": r[3], "san": r[4],
                "uci": r[5], "fen_before": r[6], "fen_after": _fen_after(r[6], r[5]), "phase": r[7],
                "best_uci": r[8], "best_san": _best_san(r[6], r[8]),
                "cp_best": r[9], "cp_played": r[10], "expected_points_lost": r[11],
                "classification": r[12],
                "is_key_moment": r[13] is not None, "reasons": r[13] or [],
                "explanation": r[14], "explanation_flagged": r[15],
                "explanation_current": current, "explanation_checked_claims": r[19],
                "explanation_fields": r[21],
            })
        keys = ("id", "white", "black", "result", "opening", "eco", "played_on")
        return {**dict(zip(keys, g, strict=True)), "moves": moves}

    @app.post("/api/moves/{move_id}/explain")
    def explain_move(move_id: int, regenerate: bool = False) -> dict:
        client = client_factory()
        model = getattr(client, "model", "unknown")
        style = default_style()
        with connect() as conn:
            row = conn.execute(
                "SELECT f.facts, m.fen_before FROM moves m JOIN facts f ON f.move_id = m.id"
                " WHERE m.id = %s", (move_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "explanations exist only for key moments")
            facts, fen = row
            fingerprint = prompt_hash(facts, style)
            if not regenerate:
                # Served from the cache only if the same model, prompt and checker wrote it.
                cached = conn.execute(
                    "SELECT body, flagged, model, checked_claims, false_claims, fields FROM explanations"
                    " WHERE move_id = %s AND model = %s AND prompt_hash = %s"
                    " AND checker_version = %s ORDER BY id DESC LIMIT 1",
                    (move_id, model, fingerprint, CHECKER_VERSION),
                ).fetchone()
                if cached:
                    return {"body": cached[0], "flagged": cached[1], "model": cached[2],
                            "checked_claims": cached[3], "false_claims": cached[4],
                            "fields": cached[5], "cached": True, "current": True}
        # The connection is closed here: a model call can take a minute and must not hold one.
        line = line_to_uci(fen, facts.get("best_line", {}).get("line_san", ""))
        try:
            result = explain(facts, client, best_line_uci=line,  # type: ignore[arg-type]
                             style=style)
        except LLMError as exc:
            raise HTTPException(503, f"local model unavailable: {exc}") from exc
        with connect() as conn:
            save_explanation(
                conn, move_id, model, result.text, result.flagged, result.attempts,
                style=style, prompt_hash=fingerprint, checker_version=CHECKER_VERSION,
                checked_claims=result.checked_claims, false_claims=result.false_claims,
                fields=result.fields,
            )
            conn.commit()
        return {"body": result.text, "flagged": result.flagged, "model": model,
                "checked_claims": result.checked_claims, "false_claims": result.false_claims,
                "fields": result.fields or None, "cached": False, "current": True}

    @app.post("/api/moves/{move_id}/guess")
    def guess_move(move_id: int, body: GuessBody) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT m.fen_before, e.best_uci, e.cp_best, e.engine_depth, m.uci, e.cp_played"
                " FROM moves m JOIN evaluations e ON e.move_id = m.id WHERE m.id = %s",
                (move_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "no such move")
        fen, best_uci, cp_best, depth, played_uci, cp_played = row
        try:
            result = score_guess(fen, body.uci, best_uci, cp_best, depth, engine,
                                 played_uci=played_uci, cp_played=cp_played)
        except ENGINE_FAILURES as exc:
            log.exception("engine failed scoring a guess on move %s", move_id)
            raise HTTPException(503, f"engine unavailable: {exc}") from exc
        except Exception:
            log.exception("unexpected error scoring a guess on move %s", move_id)
            raise
        return {**asdict(result), "best_san": _best_san(fen, best_uci)}

    @app.post("/api/moves/{move_id}/chat")
    def chat_move(move_id: int, body: ChatBody) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT m.fen_before, m.uci, e.best_uci, e.cp_best, e.cp_played,"
                " e.engine_depth, f.facts"
                " FROM moves m JOIN evaluations e ON e.move_id = m.id"
                " LEFT JOIN facts f ON f.move_id = m.id WHERE m.id = %s",
                (move_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "no such move")
        fen, played, best_uci, cp_best, cp_played, depth, stored = row
        try:
            if stored is not None:  # key moment: facts are already stored
                facts = stored
                line = line_to_uci(fen, facts.get("best_line", {}).get("line_san", ""))
            else:
                facts, line = facts_for_move(
                    fen, played, best_uci, cp_best, cp_played, depth, engine
                )
            result = answer_question(
                facts, line, fen, body.question,
                [t.model_dump() for t in body.history], client_factory(),  # type: ignore[arg-type]
            )
        except LLMError as exc:
            raise HTTPException(503, f"local model unavailable: {exc}") from exc
        except ENGINE_FAILURES as exc:
            log.exception("engine failed preparing a chat answer on move %s", move_id)
            raise HTTPException(503, f"engine unavailable: {exc}") from exc
        except Exception:
            log.exception("unexpected error answering a chat question on move %s", move_id)
            raise
        return {"body": result.text, "flagged": result.flagged}

    analysis_cache = AnalysisCache()

    @app.post("/api/analysis")
    def analyse_position(body: AnalysisBody) -> dict:
        board = chess.Board(body.fen)
        key = (board.fen(), body.depth, body.lines)
        cached = analysis_cache.get(key)
        if cached is not None:
            return cached

        def run(b: chess.Board, depth: int, lines: int):
            return engine.analyse_background(b, depth, multipv=lines, time=ANALYSIS_TIME_CAP)

        try:
            result = analyse_fen(body.fen, body.depth, body.lines, run)
            if not result["game_over"]:
                result["version"] = engine.version  # only known once the search started it
        except EngineBusy as exc:
            raise HTTPException(503, "engine busy") from exc
        except ENGINE_FAILURES as exc:
            log.exception("engine failed analysing a position")
            raise HTTPException(503, f"engine unavailable: {exc}") from exc
        except Exception:
            log.exception("unexpected error analysing a position")
            raise
        if result["game_over"] or result["lines"]:
            analysis_cache.set(key, result)
        return result

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/stats")
        def stats_page() -> FileResponse:
            return FileResponse(WEB_DIR / "stats.html")

    return app


app = create_app()
