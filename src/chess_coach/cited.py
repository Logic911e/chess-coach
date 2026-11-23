"""Explanations as cited sentences.

The model does not write free text. It returns sentences, each with the numbers of the statements
it rests on:  {"sentences": [{"text": "...", "cites": [1, 4]}]}.  Plain code then decides which
sentences survive, with no second model call and no retry:

  - a sentence that cites nothing, or cites a statement that does not exist, is dropped;
  - a sentence that names a square, a move or a number that its cited statements do not contain
    is dropped;
  - a sentence that uses a strategy word ("pressure", "control", "initiative", ...) that its cited
    statements do not use is dropped.

If too little survives, the explanation is built straight from the statements, which cannot invent
anything. This targets vagueness and invention directly. It does not make a sentence true: a
sentence can cite a statement and still misread it, so the board checks in claims.py and
factcheck.py still run on what is kept.
"""

from __future__ import annotations

import json
import re

from chess_coach.narrative import render_facts

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "cites": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "cites"],
            },
        }
    },
    "required": ["sentences"],
}

CITED_SYSTEM_PROMPT = """\
You are a chess coach explaining one move to an improving club player.

You are given a numbered list of verified statements about the position and the move.
Reply with JSON only, in this shape:
{"sentences": [{"text": "...", "cites": [1, 4]}, {"text": "...", "cites": [2]}]}

Rules:
- Write 2 to 4 sentences. Each sentence lists in "cites" the numbers of the statements it rests on.
  Put the numbers only in "cites". Never write a statement number, or the word "statement",
  inside the text of a sentence.
- A sentence may say only what its cited statements say. Copy colours, pieces, squares, moves
  and numbers exactly as they are written there.
- Do not add any fact, move, square, number, plan or judgement that is not in the statements.
  Do not talk about general ideas such as control of the centre, pressure, initiative, space or
  development unless a cited statement says it.
- Start with how good the move was, then say why, then what the engine's best move did better.
- If the statements give little to say, write fewer sentences."""

MIN_SENTENCES = 2  # fewer than this survive: use the statements themselves

_SQUARE = re.compile(r"\b[a-h][1-8]\b")
_MOVE = re.compile(
    r"\b(?:O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?)"
    r"[+#]?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Stems of words that describe a general idea. Each may appear only if a cited statement has it.
_VAGUE = ("control", "pressure", "initiative", "space", "develop", "solid", "flexib", "central",
          "centre", "center", "momentum", "coordinat", "activity", "active", "strateg",
          "positional", "dynamic", "comfortable", "harmon", "tempo",
          # praise that says nothing the facts do not
          "effective", "powerful", "optimal", "beneficial", "favorabl", "favourabl",
          "advantageous", "improv", "enhanc", "promising", "strong", "defensive", "tactical")


def statements_for(facts: dict) -> list[str]:
    """The numbered statements the model sees. Citations refer to these, so the prompt and the
    grounding check must both use this one list."""
    return render_facts(facts, True)


def build_messages(facts: dict) -> list[dict]:
    lines = "\n".join(f"{i}. {s}" for i, s in enumerate(statements_for(facts), 1))
    return [
        {"role": "system", "content": CITED_SYSTEM_PROMPT},
        {"role": "user", "content": "Statements:\n" + lines + "\n\nExplain this move."},
    ]


def parse(raw: str) -> list[dict] | None:
    """The sentences in the model's reply, or None if the reply is not the expected shape."""
    try:
        data = json.loads(raw)
        items = data["sentences"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        cites = item.get("cites")
        cites = [c for c in cites if isinstance(c, int) and not isinstance(c, bool)] \
            if isinstance(cites, list) else []
        text = strip_citations(item["text"].strip())
        if text:
            out.append({"text": text, "cites": cites})
    return out


_CITE_PAREN = re.compile(r"\s*\((?:[^()]*\b(?:cite[sd]?|statements?)\b[^()]*)\)", re.IGNORECASE)
_CITE_PHRASE = re.compile(
    r",?\s*\b(?:as\s+)?(?:stated|noted|mentioned|shown|given|listed|per|see|according to)"
    r"\s+(?:in\s+)?(?:statements?\s+)?\d+(?:\s*(?:,|and|&)\s*\d+)*", re.IGNORECASE)
_CITE_BARE = re.compile(r"\s*\(?\bstatements?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*\)?", re.IGNORECASE)


def strip_citations(text: str) -> str:
    """Remove statement numbers the model wrote into the sentence, such as "(cites: 3)" or
    "as stated in statement 1". They belong in "cites", and they must not count as numbers."""
    for rx in (_CITE_PAREN, _CITE_PHRASE, _CITE_BARE):
        text = rx.sub("", text)
    return re.sub(r"\s{2,}", " ", text).replace(" ,", ",").replace(" .", ".").strip()


def _moves(text: str) -> set[str]:
    return {m.rstrip("+#") for m in _MOVE.findall(text)}


def ground(sentence: dict, statements: list[str]) -> str | None:
    """None if the sentence is supported, otherwise why it is not.

    It must cite at least one real statement, and every square, move, number and strategy word in
    it must appear somewhere in the statements. The check is against all the statements and not
    only the cited ones, because the 7B model cites loosely: it will cite the rating for a
    sentence that names the move, which is untidy but not invented. `supported_by_cites` says
    whether the citations alone would have been enough."""
    cites = sentence["cites"]
    if not cites:
        return "cites nothing"
    if any(not 1 <= c <= len(statements) for c in cites):
        return "cites a statement that does not exist"
    return _unsupported(sentence["text"], " ".join(statements))


def supported_by_cites(sentence: dict, statements: list[str]) -> bool:
    """True if the cited statements alone contain everything the sentence names."""
    cites = [c for c in sentence["cites"] if 1 <= c <= len(statements)]
    return bool(cites) and _unsupported(
        sentence["text"], " ".join(statements[c - 1] for c in cites)) is None


def _unsupported(text: str, evidence: str) -> str | None:
    extra = set(_SQUARE.findall(text)) - set(_SQUARE.findall(evidence))
    if extra:
        return f"names {', '.join(sorted(extra))}, which its statements do not"
    extra = _moves(text) - _moves(evidence)
    if extra:
        return f"names the move {', '.join(sorted(extra))}, which its statements do not"
    extra = set(_NUMBER.findall(text)) - set(_NUMBER.findall(evidence))
    if extra:
        return f"uses the number {', '.join(sorted(extra))}, which its statements do not"
    lowered, ev = text.lower(), evidence.lower()
    for stem in _VAGUE:
        if stem in lowered and stem not in ev:
            return f"talks about '{stem}', which its statements do not"
    return None


def template(statements: list[str]) -> str:
    """The explanation straight from the statements: the rating, the move, and what was better.
    Used when too few model sentences survive. It cannot say anything the facts do not."""
    keep = [statements[0]]
    for s in statements[1:]:
        if s.startswith("The move played is") or " should have played " in s:
            keep.append(s)
        elif s.startswith("The engine's best line is") and len(s.split()) <= 16:
            keep.append(s)  # a short line reads well; a long one is a wall of moves
    return " ".join(keep)


def join_text(sentences: list[dict]) -> str:
    """The kept sentences as plain text, each ending in a full stop."""
    parts = []
    for s in sentences:
        t = s["text"].strip()
        parts.append(t if t[-1] in ".!?" else t + ".")
    return " ".join(parts)
