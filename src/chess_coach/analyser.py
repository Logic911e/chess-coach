"""Analyse a whole game and keep only the moments worth explaining.

One engine call per position is enough: the evaluation of the position AFTER a
move is the evaluation of the next position (sign flipped, because the side to
move changes). So N moves cost N+1 analyses, not 2N.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Protocol

import chess
import chess.pgn

from chess_coach import features as cf
from chess_coach.engine import DEFAULT_DEPTH, Analysis


class SupportsAnalyse(Protocol):
    def analyse(
        self, board: chess.Board, depth: int | None = ..., time: float | None = ..., multipv: int = ...
    ) -> list[Analysis]: ...


@dataclass(frozen=True)
class Thresholds:
    mistake_loss: float = 0.10  # expected points lost above this is a mistake/blunder
    swing: float = 0.15  # change in White's win probability across the move
    brilliant_max_loss: float = 0.02  # "near-best": no worse than an excellent move
    brilliant_min_sacrifice: int = 2  # net material given up (pawns), after the reply
    brilliant_max_prior_wp: float = 0.90  # not already crushing before the move
    brilliant_min_wp_after: float = 0.50  # still at least equal afterwards


@dataclass
class MoveRecord:
    ply: int  # 1 = White's first move
    move_number: int
    color: str  # "white" | "black"
    san: str
    uci: str
    fen_before: str
    best_uci: str
    best_line_uci: list[str]  # engine principal variation from the position, UCI
    cp_best: int  # mover perspective, mate capped
    cp_played: int
    expected_points_lost: float
    classification: str
    reasons: list[str] = field(default_factory=list)  # empty = not a key moment
    facts: dict | None = None  # only built for key moments

    @property
    def is_key(self) -> bool:
        return bool(self.reasons)


@dataclass
class GameAnalysis:
    headers: dict[str, str]
    moves: list[MoveRecord]

    @property
    def key_moments(self) -> list[MoveRecord]:
        return [m for m in self.moves if m.is_key]


def _white_wp(cp_mover: float, white_to_move: bool, k: float) -> float:
    wp = cf.win_prob(cp_mover, k)
    return wp if white_to_move else 1.0 - wp


def _net_material_given_up(board: chess.Board, move: chess.Move, reply_uci: str | None) -> int:
    """Mover's material change over (move, best reply). Positive = material lost.

    Looking one reply deep means an even trade (Bxc3 bxc3) counts as zero, while
    a real sacrifice (Nxf7 Kxf7) counts as a loss.
    """
    sign = 1 if board.turn == chess.WHITE else -1
    before = sign * cf.material_balance(board)
    b = board.copy(stack=False)
    b.push(move)
    if reply_uci:
        reply = chess.Move.from_uci(reply_uci)
        if reply in b.legal_moves:
            b.push(reply)
    return before - sign * cf.material_balance(b)


def analyse_game(
    pgn_text: str,
    engine: SupportsAnalyse,
    depth: int = DEFAULT_DEPTH,
    k: float = 0.004,
    thresholds: Thresholds | None = None,
) -> GameAnalysis:
    th = thresholds or Thresholds()
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("No game found in PGN.")
    moves = list(game.mainline_moves())
    if not moves:
        raise ValueError("PGN contains no moves.")

    # boards[i] is the position before moves[i]; boards[-1] is the final position.
    boards = [game.board()]
    for mv in moves:
        following = boards[-1].copy(stack=False)
        following.push(mv)
        boards.append(following)

    analyses: list[list[Analysis] | None] = [
        None if b.is_game_over() else engine.analyse(b, depth=depth) for b in boards
    ]

    records: list[MoveRecord] = []
    for i, move in enumerate(moves):
        board, after = boards[i], boards[i + 1]
        lines = analyses[i]
        if not lines:
            raise ValueError(f"No engine line for position before ply {i + 1}.")
        best = lines[0]
        cp_best = best.cp_capped

        if move.uci() == best.best_move:
            cp_played = cp_best
        elif after.is_checkmate():
            cp_played = cf.MATE_CP
        elif after.is_game_over():
            cp_played = 0  # stalemate or other draw
        else:
            nxt = analyses[i + 1]
            assert nxt  # the position after a non-final, non-terminal move was analysed
            # Flip sign: the next position is scored for the opponent. Never allow the
            # played move to look better than the engine's best (search noise).
            cp_played = min(cp_best, -nxt[0].cp_capped)

        loss = cf.expected_points_lost(cp_best, cp_played, k)
        label = cf.classify(loss)
        white = board.turn == chess.WHITE

        reasons: list[str] = []
        if loss > th.mistake_loss:
            reasons.append(label)  # "mistake" or "blunder"
        swing = abs(_white_wp(cp_best, white, k) - _white_wp(cp_played, white, k))
        if swing >= th.swing:
            reasons.append("big_swing")

        next_lines = analyses[i + 1]
        reply = next_lines[0].best_move if next_lines else None
        if (
            loss <= th.brilliant_max_loss
            and cf.win_prob(cp_best, k) <= th.brilliant_max_prior_wp
            and cf.win_prob(cp_played, k) >= th.brilliant_min_wp_after
            and _net_material_given_up(board, move, reply) >= th.brilliant_min_sacrifice
        ):
            reasons.append("brilliant")

        facts = None
        if reasons:
            facts = cf.build_facts(
                board.fen(), move.uci(), best.best_move, cp_best, cp_played,
                best_line_uci=best.pv, k=k,
            )
        records.append(
            MoveRecord(
                ply=i + 1,
                move_number=board.fullmove_number,
                color="white" if white else "black",
                san=board.san(move),
                uci=move.uci(),
                fen_before=board.fen(),
                best_uci=best.best_move,
                best_line_uci=best.pv,
                cp_best=cp_best,
                cp_played=cp_played,
                expected_points_lost=round(loss, 3),
                classification=label,
                reasons=reasons,
                facts=facts,
            )
        )
    return GameAnalysis(headers=dict(game.headers), moves=records)
