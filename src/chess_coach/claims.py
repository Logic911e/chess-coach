"""Objective checks on an explanation's claims, used by the evaluation harness.

Two kinds of false claim can be verified mechanically against the board:
- naming a move that is not legal anywhere along the engine line, and
- saying a piece is on a square when no relevant position has it there.
Both are checked against the same set of "truth" positions for every condition,
so the comparison between prompts is fair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from chess_coach import features as cf

_PIECES = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}
# "the white knight on f6", "bishop at c4", "queens on d8"
_PLACEMENT = re.compile(
    r"\b(?:(white|black)(?:'s)?\s+)?(pawn|knight|bishop|rook|queen|king)s?\s+(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimReport:
    illegal_moves: list[str]
    false_placements: list[str]

    @property
    def count(self) -> int:
        return len(self.illegal_moves) + len(self.false_placements)


def threat_board(start: chess.Board) -> list[chess.Board]:
    """The position if the side to move passed. Naming a threat ("...g6 stops Qxf7")
    mentions a move that is only legal in this hypothetical, so it must be allowed."""
    if start.is_check():
        return []
    passed = start.copy(stack=False)
    passed.push(chess.Move.null())
    return [passed]


def truth_boards(fen: str, played_uci: str, best_line_uci: list[str]) -> list[chess.Board]:
    """Every position a correct explanation may talk about."""
    start = chess.Board(fen)
    boards = cf.positions_along_line(start, [played_uci])
    boards += cf.positions_along_line(start, best_line_uci)[1:]
    return boards + threat_board(start)


def false_placements(text: str, boards: list[chess.Board]) -> list[str]:
    bad = []
    for m in _PLACEMENT.finditer(text):
        color_word, piece_word, square = m.groups()
        piece_type = _PIECES[piece_word.lower()]
        sq = chess.parse_square(square.lower())
        color = None if color_word is None else color_word.lower() == "white"
        ok = any(
            (p := b.piece_at(sq)) is not None
            and p.piece_type == piece_type
            and (color is None or p.color == color)
            for b in boards
        )
        if not ok:
            bad.append(m.group(0))
    return bad


def check_claims(text: str, boards: list[chess.Board]) -> ClaimReport:
    return ClaimReport(
        illegal_moves=cf.find_illegal_moves(text, boards),
        false_placements=false_placements(text, boards),
    )
