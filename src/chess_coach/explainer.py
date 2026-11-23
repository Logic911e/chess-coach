"""Turn a facts record into a short explanation, and check it before it reaches the user.

The model sees only the facts. Every reply is checked for two kinds of objective error:
moves that are not legal in the position or along the engine line, and pieces placed on
squares that never hold them (see claims.py). On either, we ask again, and flag the result
if the retries run out. This does NOT catch wrong judgements or vague filler.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import chess

from chess_coach.claims import check_claims, truth_boards
from chess_coach.llm import ChatClient, Message
from chess_coach.narrative import render_facts

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


STATEMENTS_SYSTEM_PROMPT = """\
You are a chess coach explaining one move to an improving club player.

You are given a numbered list of verified statements about the position and the move.
Write a short explanation that uses ONLY those statements.

Rules:
- Do not add any fact, move, square, plan or judgement that is not in the statements.
- Keep every piece colour and square exactly as written.
- Name a move only if it appears in the statements.
- Start with how good the move was, then say why, then what the engine's best move did better.
- 3 to 5 sentences. Plain language. No lists, no headings."""


STATEMENTS_STRICT_SYSTEM_PROMPT = """\
You are a chess coach explaining one move to an improving club player.

You are given a numbered list of verified statements about the position and the move.
Write a short explanation that uses ONLY those statements.

Rules:
- Every sentence must rest on at least one numbered statement. If you cannot point to one,
  do not write that sentence.
- Do not add any fact, move, square, plan or judgement that is not in the statements. In
  particular, do not talk about central control, development, activity, space, initiative,
  pressure or the engine's later moves unless a statement says so.
- Keep every piece colour and square exactly as written.
- Name a move only if it appears in the statements.
- Start with how good the move was, then say why, then what the engine's best move did better.
- If the statements give you little to say, write fewer sentences: 2 to 4 in all.
  Plain language. No lists, no headings."""

# style -> (system prompt, include the richer statements)
_STATEMENT_STYLES = {
    "statements": (STATEMENTS_SYSTEM_PROMPT, False),
    "statements_strict": (STATEMENTS_STRICT_SYSTEM_PROMPT, False),
    "statements_rich": (STATEMENTS_STRICT_SYSTEM_PROMPT, True),
}


def default_style() -> str:
    """The statement style the app uses. Set CHESS_COACH_STYLE to switch it without code changes:
    statements (default), statements_strict or statements_rich."""
    style = os.environ.get("CHESS_COACH_STYLE", "statements")
    if style not in _STATEMENT_STYLES:
        raise ValueError(
            f"CHESS_COACH_STYLE={style!r} is not one of {', '.join(_STATEMENT_STYLES)}"
        )
    return style


def build_messages(facts: dict, style: str = "json") -> list[Message]:
    """style 'json' = raw facts record; 'statements' = plain-English statements (narrative.py);
    'statements_strict' = same statements, stricter prompt; 'statements_rich' = stricter prompt
    plus extra statements (material, king safety, hanging pieces, development)."""
    if style in _STATEMENT_STYLES:
        prompt, rich = _STATEMENT_STYLES[style]
        lines = "\n".join(f"{i}. {s}" for i, s in enumerate(render_facts(facts, rich), 1))
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Statements:\n" + lines + "\n\nExplain this move."},
        ]
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
    false_placements: list[str] = field(default_factory=list)
    attempts: int = 1


def boards_for_check(facts: dict, best_line_uci: list[str] | None) -> list[chess.Board]:
    """Positions in which a named move counts as legal: start, after the played move,
    along the engine line, and the "side passes" position (for naming threats)."""
    return truth_boards(facts["fen"], facts["played"]["uci"], best_line_uci or [])


def explain(
    facts: dict,
    client: ChatClient,
    best_line_uci: list[str] | None = None,
    max_retries: int = 2,
    style: str = "json",
) -> Explanation:
    boards = boards_for_check(facts, best_line_uci)
    return run_checked(build_messages(facts, style), client, boards, max_retries)


def run_checked(
    messages: list[Message],
    client: ChatClient,
    boards: list[chess.Board],
    max_retries: int = 2,
) -> Explanation:
    """Ask the model, check the reply against `boards`, and re-ask with the problems named."""
    report = check_claims("", boards)
    text = ""
    for attempt in range(1, max_retries + 2):
        text = client.chat(messages)
        report = check_claims(text, boards)
        if report.count == 0:
            return Explanation(text=text, flagged=False, attempts=attempt)
        problems = []
        if report.illegal_moves:
            problems.append(f"these moves are not legal here: {', '.join(report.illegal_moves)}")
        if report.false_placements:
            problems.append(f"these piece placements are wrong: {', '.join(report.false_placements)}")
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    "Check failed: " + "; ".join(problems) + ". Rewrite the explanation using "
                    "only moves and squares that appear in the facts."
                ),
            },
        ]
    return Explanation(
        text=text,
        flagged=True,
        illegal_moves=report.illegal_moves,
        false_placements=report.false_placements,
        attempts=max_retries + 1,
    )
