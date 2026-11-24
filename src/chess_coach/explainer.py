"""Turn a facts record into a short explanation, and check it before it reaches the user.

The model sees only the facts. Every reply is checked for three kinds of objective error:
moves that are not legal in the position or along the engine line, pieces placed on squares
that never hold them (see claims.py), and tactical claims the board contradicts, such as "the
knight on f3 is undefended" when it is defended (see factcheck.py). On any of these we ask again,
and flag the result if the retries run out. This does NOT catch strategy claims, wrong
judgements that are not about the board, or vague filler.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import chess

from chess_coach import cited, fields
from chess_coach.claims import check_claims, truth_boards
from chess_coach.factcheck import check_text
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
- Always say which side you mean. Write "White" or "Black" for every move and piece; never
  "the engine's best move is Qf5" without saying for whom. A move belongs to the side to move,
  and its targets belong to the other side.
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
- Always say which side you mean. Write "White" or "Black" for every move and piece; never
  "the engine's best move is Qf5" without saying for whom. A move belongs to the side to move,
  and its targets belong to the other side.
- Name a move only if it appears in the statements.
- Start with how good the move was, then say why, then what the engine's best move did better.
- If the statements give you little to say, write fewer sentences: 2 to 4 in all.
  Plain language. No lists, no headings."""

# style -> (system prompt, include the richer statements)
_STATEMENT_STYLES = {
    "statements": (STATEMENTS_SYSTEM_PROMPT, False),
    "statements_strict": (STATEMENTS_STRICT_SYSTEM_PROMPT, False),
    "statements_rich": (STATEMENTS_STRICT_SYSTEM_PROMPT, True),
    "cited": (cited.CITED_SYSTEM_PROMPT, True),  # structured sentences; see cited.py
    "fields": (fields.FIELDS_SYSTEM_PROMPT, True),  # reason and better as fields; see fields.py
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
    if style == "cited":
        return cited.build_messages(facts)
    if style == "fields":
        return fields.build_messages(facts)
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
    flagged: bool  # True = a check still failed after all retries
    illegal_moves: list[str] = field(default_factory=list)
    false_placements: list[str] = field(default_factory=list)
    false_claims: list[str] = field(default_factory=list)  # tactical claims the board contradicts
    checked_claims: int = 0  # tactical claims read and tested in the final text
    attempts: int = 1
    dropped: list[str] = field(default_factory=list)  # cited style: sentences removed, and why
    fallback: bool = False  # cited style: too little survived, so the text is the statements
    sentences: list[dict] = field(default_factory=list)  # cited style: kept text, cites, exact
    # fields style: [{"key", "label", "text", "source": "code" | "model" | "facts"}], in order
    fields: list[dict] = field(default_factory=list)


def prompt_hash(facts: dict, style: str) -> str:
    """A short fingerprint of exactly what the model is asked: system prompt plus statements.
    It changes when the style, the prompt wording or the facts change."""
    messages = build_messages(facts, style)
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]


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
    if style == "cited":
        return explain_cited(facts, client, best_line_uci)
    if style == "fields":
        return explain_fields(facts, client, best_line_uci)
    boards = boards_for_check(facts, best_line_uci)
    return run_checked(
        build_messages(facts, style), client, boards, max_retries,
        facts=facts, best_line_uci=best_line_uci,
    )


def _vet(
    sentences: list[dict], statements: list[str], facts: dict,
    best_line_uci: list[str] | None, dropped: list[str], need_cites: bool,
) -> tuple[list[dict], int]:
    """Keep the sentences that are supported by the statements and pass the board checks.
    Returns them and the number of tactical claims that were tested. Why each other sentence
    went is appended to `dropped`."""
    kept = []
    for s in sentences:
        reason = cited.ground(s, statements, need_cites)
        if reason:
            dropped.append(f"{reason}: {s['text']}")
        else:
            if need_cites:
                s["exact"] = cited.supported_by_cites(s, statements)
            kept.append(s)
    # Board checks on what is left: illegal moves and wrong piece squares, sentence by sentence.
    boards = boards_for_check(facts, best_line_uci)
    clean = []
    for s in kept:
        report = check_claims(s["text"], boards)
        if report.count:
            bad = [*report.illegal_moves, *report.false_placements]
            dropped.append(f"fails the board check ({', '.join(bad)}): {s['text']}")
        else:
            clean.append(s)
    # Tactical claims, read across the whole text so "It" keeps its meaning.
    result = check_text(cited.join_text(clean), facts, best_line_uci)
    if result.false_claims:
        problems = {f.sentence: f.problem for f in result.false_claims}
        still = []
        for s in clean:
            hit = next((b for b in problems if b in s["text"] or s["text"] in b), None)
            if hit:
                dropped.append(f"{problems[hit]}: {s['text']}")
            else:
                still.append(s)
        clean = still
    return clean, result.checked


def explain_cited(
    facts: dict, client: ChatClient, best_line_uci: list[str] | None = None
) -> Explanation:
    """One model call, then deterministic filtering: keep only the sentences that are supported
    by the statements they cite and that pass the board checks. No retry."""
    statements = cited.statements_for(facts)
    raw = client.chat(cited.build_messages(facts), format=cited.SCHEMA)
    sentences = cited.parse(raw)
    dropped: list[str] = []
    if sentences is None:
        sentences = []
        dropped.append("the reply was not in the expected format")
    clean, checked = _vet(sentences, statements, facts, best_line_uci, dropped, need_cites=True)
    if len(clean) < cited.MIN_SENTENCES:
        return Explanation(
            text=cited.template(statements), flagged=False, checked_claims=checked,
            dropped=dropped, fallback=True,
        )
    return Explanation(
        text=cited.join_text(clean), flagged=False, checked_claims=checked, dropped=dropped,
        sentences=clean,
    )


def explain_fields(
    facts: dict, client: ChatClient, best_line_uci: list[str] | None = None
) -> Explanation:
    """The model writes a reason and what was better; code writes the verdict. Each model field
    is vetted sentence by sentence, and a field that fails is rewritten from the statements on its
    own, so one bad sentence does not undo the others. One model call, no retry."""
    statements = cited.statements_for(facts)
    raw = client.chat(fields.build_messages(facts), format=fields.SCHEMA)
    got = fields.parse(raw)
    dropped: list[str] = []
    if got is None:
        got = {"reason": "", "better": ""}
        dropped.append("the reply was not in the expected format")
    has_better = "best" in facts
    sentences = [{"text": t, "part": "reason"} for t in cited.split_sentences(got["reason"])]
    if has_better:
        sentences += [{"text": t, "part": "better"} for t in cited.split_sentences(got["better"])]
    elif got["better"]:
        dropped.append("the move was the engine's choice, so the 'better' field was ignored")
    kept, checked = _vet(sentences, statements, facts, best_line_uci, dropped, need_cites=False)

    out = [{"key": "verdict", "label": "Verdict", "text": fields.verdict(facts), "source": "code"}]
    reason = cited.join_text([s for s in kept if s["part"] == "reason"])
    source = "model"
    if not reason:
        reason, source = fields.fallback_reason(statements), "facts"
    if reason:
        out.append({"key": "reason", "label": "Why", "text": reason, "source": source})
    if has_better:
        better = cited.join_text([s for s in kept if s["part"] == "better"])
        source = "model"
        if not better or not fields.mentions_best(better, facts):
            if better:
                dropped.append(f"the 'better' field did not name the engine's move: {better}")
            better, source = fields.fallback_better(statements), "facts"
        if better:
            out.append({"key": "better", "label": "What was better", "text": better,
                        "source": source})
    return Explanation(
        text=" ".join(f["text"] for f in out), flagged=False, checked_claims=checked,
        dropped=dropped, fallback=any(f["source"] == "facts" for f in out), fields=out,
    )


def run_checked(
    messages: list[Message],
    client: ChatClient,
    boards: list[chess.Board],
    max_retries: int = 2,
    facts: dict | None = None,
    best_line_uci: list[str] | None = None,
) -> Explanation:
    """Ask the model, check the reply against `boards`, and re-ask with the problems named.

    With `facts`, tactical claims in the reply are checked too (see factcheck.py)."""
    report = check_claims("", boards)
    false_claims: list[str] = []
    checked = 0
    text = ""
    for attempt in range(1, max_retries + 2):
        text = client.chat(messages)
        report = check_claims(text, boards)
        if facts:
            result = check_text(text, facts, best_line_uci)
            false_claims = [f.problem for f in result.false_claims]
            checked = result.checked
        if report.count == 0 and not false_claims:
            return Explanation(text=text, flagged=False, checked_claims=checked, attempts=attempt)
        problems = []
        if report.illegal_moves:
            problems.append(f"these moves are not legal here: {', '.join(report.illegal_moves)}")
        if report.false_placements:
            problems.append(f"these piece placements are wrong: {', '.join(report.false_placements)}")
        if false_claims:
            problems.append(f"these claims are wrong: {'; '.join(false_claims)}")
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    "Check failed: " + "; ".join(problems) + ". Rewrite the explanation using "
                    "only moves, squares and claims that the facts support."
                ),
            },
        ]
    return Explanation(
        text=text,
        flagged=True,
        illegal_moves=report.illegal_moves,
        false_placements=report.false_placements,
        false_claims=false_claims,
        checked_claims=checked,
        attempts=max_retries + 1,
    )
