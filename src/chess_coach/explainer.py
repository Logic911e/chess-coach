"""Turn a facts record into a short explanation, and check it before it reaches the user.

The model sees only the facts. Every reply goes through `find_illegal_moves`;
if it names a move that is not legal in the position or along the engine line,
we ask again, and flag the result if the retries run out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import chess

from chess_coach import features as cf
from chess_coach.llm import ChatClient, Message

SYSTEM_PROMPT = """\
You are a chess coach explaining one move to an improving club player.

You are given a JSON "facts" record produced by a chess engine and a rules library.
These facts are the ONLY source of truth.

Rules:
- Use only information in the facts. If something is not in the facts, do not say it.
- Name a move only if it appears in the facts (the played move, the best move, or a move
  in best_line.line_san). Never suggest or mention any other move.
- Do not invent threats, plans, tactics, evaluations or opening names.
- Say how good the played move was using "classification". Do not quote raw numbers
  except expected_points_lost, if useful.
- If "best" is present, say what it did better. If "played" has non-empty
  leaves_own_piece_hanging or ignored_threats, explain that.
- 3 to 5 sentences. Plain language. No lists, no headings."""


def build_messages(facts: dict) -> list[Message]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Facts:\n" + json.dumps(facts, indent=1) + "\n\nExplain this move.",
        },
    ]


@dataclass
class Explanation:
    text: str
    flagged: bool  # True = still named illegal moves after all retries
    illegal_moves: list[str] = field(default_factory=list)
    attempts: int = 1


def boards_for_check(facts: dict, best_line_uci: list[str] | None) -> list[chess.Board]:
    """Positions in which a named move counts as legal: start, after the played move,
    and along the engine line."""
    start = chess.Board(facts["fen"])
    boards = cf.positions_along_line(start, [facts["played"]["uci"]])  # start + after played
    if best_line_uci:
        boards += cf.positions_along_line(start, best_line_uci)[1:]
    return boards


def explain(
    facts: dict,
    client: ChatClient,
    best_line_uci: list[str] | None = None,
    max_retries: int = 2,
) -> Explanation:
    boards = boards_for_check(facts, best_line_uci)
    messages = build_messages(facts)
    bad: list[str] = []
    text = ""
    for attempt in range(1, max_retries + 2):
        text = client.chat(messages)
        bad = cf.find_illegal_moves(text, boards)
        if not bad:
            return Explanation(text=text, flagged=False, attempts=attempt)
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"These moves are not legal here: {', '.join(bad)}. Rewrite the explanation "
                    "using only moves that appear in the facts."
                ),
            },
        ]
    return Explanation(text=text, flagged=True, illegal_moves=bad, attempts=max_retries + 1)
