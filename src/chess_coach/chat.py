"""Position-scoped chat about one move, under the same claims guardrail as explanations."""

from __future__ import annotations

import re

import chess

from chess_coach import features as cf
from chess_coach.claims import truth_boards
from chess_coach.engine_service import EngineLike
from chess_coach.explainer import Explanation, default_style, run_checked
from chess_coach.llm import ChatClient, Message
from chess_coach.narrative import render_facts

HISTORY_LIMIT = 6

CHAT_SYSTEM_PROMPT = """\
You are a chess coach answering a question from an improving club player about one move.

You are given a numbered list of verified statements about the position and the move.
Answer using ONLY those statements.

Rules:
- Do not add any fact, move, square, plan or judgement that is not in the statements.
- If the answer is not in the statements, say so plainly instead of guessing.
- Keep every piece colour and square exactly as written.
- You may repeat a move the player named, but do not suggest any other move.
- A few sentences at most. Plain language. No lists, no headings."""

_UCI = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b")


def facts_for_move(
    fen: str, played_uci: str, best_uci: str, cp_best: int, cp_played: int, depth: int,
    engine: EngineLike,
) -> tuple[dict, list[str]]:
    """Facts for any move from its stored scores; the engine line is fetched at `depth`."""
    board = chess.Board(fen)
    pv = engine.analyse(board, depth=depth)[0].pv
    line = pv if pv and pv[0] == best_uci else [best_uci]
    facts = cf.build_facts(fen, played_uci, best_uci, cp_best, cp_played, best_line_uci=line)
    return facts, line


def named_moves(fen: str, text: str) -> list[str]:
    """Legal moves (SAN or UCI) mentioned in `text`, as UCI, in order, without repeats."""
    board = chess.Board(fen)
    found: list[tuple[int, str]] = []
    for m in cf._SAN.finditer(text):
        try:
            found.append((m.start(), board.parse_san(m.group().rstrip("+#")).uci()))
        except ValueError:
            continue
    for m in _UCI.finditer(text):
        try:
            move = chess.Move.from_uci(m.group())
        except ValueError:
            continue
        if move in board.legal_moves:
            found.append((m.start(), move.uci()))
    out: list[str] = []
    for _, uci in sorted(found):
        if uci not in out:
            out.append(uci)
    return out


def answer_question(
    facts: dict, line: list[str], fen: str, question: str, history: list[dict],
    client: ChatClient,
) -> Explanation:
    rich = default_style() == "statements_rich"
    lines = "\n".join(
        f"{i}. {s}" for i, s in enumerate(render_facts(facts, rich), 1)
    )
    recent = history[-HISTORY_LIMIT:]
    messages: list[Message] = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": "Statements:\n" + lines},
        *({"role": h["role"], "content": h["content"]} for h in recent),
        {"role": "user", "content": question},
    ]
    boards = truth_boards(fen, facts["played"]["uci"], line)
    start = chess.Board(fen)
    mentioned = question + " " + " ".join(h["content"] for h in recent if h["role"] == "user")
    for uci in named_moves(fen, mentioned):
        after = start.copy(stack=False)
        after.push_uci(uci)
        boards.append(after)
    return run_checked(messages, client, boards)
