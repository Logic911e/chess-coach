"""Explanations in separate fields.

The model still writes in its own words, but into two named fields instead of one block:
    {"reason": "...", "better": "..."}
and code writes the third, the verdict, because it is a pure fact (the rating and the points lost).
Each field is then treated according to its job:

  verdict  written by code from the facts, always correct.
  reason   why the move was good or bad. Model text, vetted sentence by sentence (nothing may be
           named that the statements do not contain, no fluff, and the board checks must pass).
  better   what the engine preferred. Model text that must name the engine's move, vetted the same
           way. Left out when the move played was the engine's choice.

If a field fails, only that field is rewritten from the statements; the other fields keep the
model's words. So one bad sentence no longer sends the whole answer back to a dump of facts, and
the page can show each part in its own place.
"""

from __future__ import annotations

import json
import re

from chess_coach import cited

SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "better": {"type": "string"}},
    "required": ["reason", "better"],
}

FIELDS_SYSTEM_PROMPT = """\
You are a chess coach explaining one move to an improving club player.

You are given a numbered list of verified statements about the position and the move.
Reply with JSON only, with two fields:
{"reason": "...", "better": "..."}

- "reason": one or two sentences on WHY the move was good or bad, using only what the statements say.
- "better": one sentence on what the engine preferred and what that move does better. If the move
  played was the engine's own choice, write an empty string.

Rules:
- Use only facts from the statements. Copy colours, pieces, squares, moves and numbers exactly as
  they are written there. Do not add any move, square, number, plan or judgement of your own.
- Do not repeat the rating or the points lost; they are shown separately.
- Never write statement numbers or the word "statement".
- Never use these words: effective, optimal, strong, powerful, defensive, tactical, strategic,
  positional, pressure, control, initiative, space, development, solid, flexible, central,
  improve, beneficial, favourable, dynamic, momentum. They are not facts.
- If the statements give little to say, write less."""

_ARTICLE = {"inaccuracy": "an inaccuracy", "mistake": "a mistake", "blunder": "a blunder"}


def build_messages(facts: dict) -> list[dict]:
    lines = "\n".join(f"{i}. {s}" for i, s in enumerate(cited.statements_for(facts), 1))
    return [
        {"role": "system", "content": FIELDS_SYSTEM_PROMPT},
        {"role": "user", "content": "Statements:\n" + lines + "\n\nExplain this move."},
    ]


def parse(raw: str) -> dict[str, str] | None:
    """The two fields from the model's reply, cleaned, or None if it is not the expected shape."""
    try:
        data = json.loads(raw)
        reason, better = data["reason"], data["better"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(reason, str) or not isinstance(better, str):
        return None
    return {"reason": cited.strip_citations(reason.strip()),
            "better": cited.strip_citations(better.strip())}


def verdict(facts: dict) -> str:
    """How good the move was, written from the facts alone."""
    san = facts["played"]["san"]
    label, lost = facts["classification"], facts["expected_points_lost"]
    who = facts["side_to_move"].capitalize()
    if "best" not in facts:
        return f"{who}'s {san} is the engine's best move."
    if label in _ARTICLE:
        return f"{who}'s {san} is {_ARTICLE[label]}, losing {lost} expected points."
    return f"{who}'s {san} is rated {label}, losing {lost} expected points."


def repeats_verdict(sentence: str, facts: dict) -> bool:
    """A sentence that only restates the rating, which the verdict already says: it quotes the points
    lost, says "rated", or is a short "...is the engine's best move"."""
    low = sentence.lower()
    if "point" in low and str(facts["expected_points_lost"]) in sentence:
        return True
    if re.search(r"\brated\b", low):
        return True
    return len(sentence.split()) <= 9 and "best move" in low


def fallback_reason(statements: list[str]) -> str:
    """The reason straight from the statements, used when the model's wording fails the checks."""
    found = cited.reason_statements(statements)
    if not found:  # a quiet move that was also the engine's choice
        found = [s for s in statements if s.startswith("The move played is also")][:1]
    return " ".join(found)


def fallback_better(statements: list[str]) -> str:
    return " ".join(cited.better_statements(statements))


def mentions_best(text: str, facts: dict) -> bool:
    """Whether `text` names the engine's move, which the "better" field must do."""
    best = facts.get("best")
    if not best:
        return False
    san = re.escape(best["san"].rstrip("+#"))  # a pawn push such as g6 is just a square name
    return re.search(rf"(?<![A-Za-z0-9]){san}(?![A-Za-z0-9])", text) is not None
