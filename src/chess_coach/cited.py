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
- Never use these words: effective, optimal, strong, powerful, defensive, tactical, strategic,
  positional, pressure, control, initiative, space, development, solid, flexible, central,
  improve, beneficial, favourable, dynamic, momentum. They are not facts.
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
        # The 7B model often puts a whole paragraph into one entry, so split it into real
        # sentences. Each keeps the entry's citations, which lets one bad sentence be dropped
        # without losing the good ones around it.
        for piece in split_sentences(strip_citations(item["text"].strip())):
            out.append({"text": piece, "cites": cites})
    return out


_CITE_PAREN = re.compile(r"\s*\((?:[^()]*\b(?:cite[sd]?|statements?)\b[^()]*)\)", re.IGNORECASE)
_CITE_PHRASE = re.compile(
    r",?\s*\b(?:as\s+)?(?:stated|noted|mentioned|shown|given|listed|per|see|according to)"
    r"\s+(?:in\s+)?(?:statements?\s+)?\d+(?:\s*(?:,|and|&)\s*\d+)*", re.IGNORECASE)
_CITE_BARE = re.compile(r"\s*\(?\bstatements?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*\)?", re.IGNORECASE)


# A sentence ends at . ! or ?, but not after a move number such as "4." in "4. Nf3".
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\d\.)\s+(?=[A-Z\"'])")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def strip_citations(text: str) -> str:
    """Remove statement numbers the model wrote into the sentence, such as "(cites: 3)" or
    "as stated in statement 1". They belong in "cites", and they must not count as numbers."""
    for rx in (_CITE_PAREN, _CITE_PHRASE, _CITE_BARE):
        text = rx.sub("", text)
    return re.sub(r"\s{2,}", " ", text).replace(" ,", ",").replace(" .", ".").strip()


def _moves(text: str) -> set[str]:
    return {m.rstrip("+#") for m in _MOVE.findall(text)}


def moves_in(text: str) -> set[str]:
    """The moves named in a text, without check or mate signs."""
    return _moves(text)


def ground(sentence: dict, statements: list[str], need_cites: bool = True) -> str | None:
    """None if the sentence is supported, otherwise why it is not.

    It must cite at least one real statement, and every square, move, number and strategy word in
    it must appear somewhere in the statements. The check is against all the statements and not
    only the cited ones, because the 7B model cites loosely: it will cite the rating for a
    sentence that names the move, which is untidy but not invented. `supported_by_cites` says
    whether the citations alone would have been enough."""
    cites = sentence.get("cites", [])
    if need_cites:  # the fields style has no citations: only what is named is checked
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


_RATING_NOTE = re.compile(r"\s*\(0 = no loss, 1 = the whole game\)")
_SIDE_PREFIX = re.compile(r"^(?:White|Black) to move\.\s*")


def _is_reason(s: str) -> bool:
    return (s.startswith("After ") or " was already under threat" in s
            or " gives check" in s or " is checkmate" in s)


def clean_rating(statement: str) -> str:
    """The rating statement without "White to move." and the scale note."""
    return _RATING_NOTE.sub("", _SIDE_PREFIX.sub("", statement))


def reason_statements(statements: list[str]) -> list[str]:
    """Up to three statements saying why the move was good or bad."""
    best = next((i for i, s in enumerate(statements) if s.startswith("The engine's best move is")),
                len(statements))
    return [s for s in statements[1:best] if _is_reason(s)][:3]


def better_statements(statements: list[str]) -> list[str]:
    """What the engine preferred, and up to two reasons it was better. Empty if the move played
    was the engine's choice."""
    should = next((i for i, s in enumerate(statements) if " should have played " in s), None)
    if should is None:
        return []
    best = next((i for i, s in enumerate(statements) if s.startswith("The engine's best move is")),
                len(statements))
    return [statements[should], *[s for s in statements[best + 1:should] if _is_reason(s)][:2]]


def template(statements: list[str]) -> str:
    """The explanation straight from the statements, used when too few model sentences survive:
    the rating, the move, up to three reasons it was good or bad, what the engine preferred, and
    up to two reasons for that. It cannot say anything the facts do not. Only the rating line is
    reworded, to drop the scale note."""
    out = [clean_rating(statements[0])]
    out += [s for s in statements[1:] if s.startswith("The move played is") and "also" not in s][:1]
    out += reason_statements(statements)
    better = better_statements(statements)
    if better:
        out += better
    else:  # the move played was the engine's choice
        out += [s for s in statements if s.startswith("The move played is also")][:1]
    line = next((s for s in statements if s.startswith("The engine's best line is")), None)
    if line and len(line.split()) <= 16:
        out.append(line)  # a short line reads well; a long one is a wall of moves
    return " ".join(out)


def join_text(sentences: list[dict]) -> str:
    """The kept sentences as plain text, each ending in a full stop."""
    parts = []
    for s in sentences:
        t = s["text"].strip()
        parts.append(t if t[-1] in ".!?" else t + ".")
    return " ".join(parts)
