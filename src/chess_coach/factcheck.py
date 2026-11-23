"""Check an explanation's tactical claims against the board.

claims.py catches two kinds of error: illegal moves and pieces named on squares they never occupy.
This module catches a third: claims about what the pieces are doing. It reads sentences such as
"the black knight on f6 attacks the white queen on h5" or "the white knight on f3 becomes
undefended" and tests each one with python-chess.

Only claims that can be pinned down are read: a colour, a piece and a square, or a named move.
Strategy talk ("controls the centre") is not read and not judged. A claim is reported only when it
is false in every position the explanation may be talking about (the start, after the move played,
after the engine's first move, and the "side passes" position) and also further along the engine
line, so a true claim is never flagged just because of the position it was checked in.

No engine is needed: everything comes from the facts record and the engine line the explainer
already has. Claims that need a deeper look ahead (what happens after the move played) are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from chess_coach import features as cf
from chess_coach.claims import threat_board, truth_boards

PIECE = r"(?:pawn|knight|bishop|rook|queen|king)"
SAN = (r"(?:O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?"
       r"|[a-h][1-8](?:=[QRBN])?)[+#]?")
_SAN_MENTION = re.compile(rf"(?<!on )(?<!at )(?<!to )(?<!from )(?<!the )\b({SAN})(?![\w-])")
_BEST_PHRASE = re.compile(
    r"engine(?:'s)?\s+(?:best|preferred|top|suggested)\s+(?:move|line|continuation)"
    r"|engine\s+(?:prefers|suggests|recommends|favou?rs)|\bbest\s+move\b", re.IGNORECASE)
_PIECES = {"pawn": chess.PAWN, "knight": chess.KNIGHT, "bishop": chess.BISHOP,
           "rook": chess.ROOK, "queen": chess.QUEEN, "king": chess.KING}
_GOOD = {"best", "excellent", "good"}
_VALUE = {"pawn": 1, "knight": 3, "bishop": 3, "rook": 5, "queen": 9, "piece": 3, "material": 1}
_UNDEFENDED = {"undefended", "unprotected", "loose"}


def _ph(n: str) -> str:
    """A piece phrase with its colour, such as 'the white knight on f6'. Groups c<n> p<n> s<n>."""
    return (rf"(?:the\s+)?(?P<c{n}>white|black)(?:'s)?\s+(?P<p{n}>{PIECE})s?\s+"
            rf"(?:on|at)\s+(?P<s{n}>[a-h][1-8])\b")


def _pc(m: re.Match, n: str) -> dict:
    return {"color": m.group(f"c{n}").lower(), "piece": m.group(f"p{n}").lower(),
            "square": m.group(f"s{n}").lower()}


_SUBJ = (rf"(?P<subj>It|Which|This\s+(?:\w+\s+)?move|The\s+move|{SAN}|"
         rf"(?:The\s+)?(?:(?:white|black)\s+)?{PIECE})")
_ATTACK = re.compile(
    rf"\b{_SUBJ}\s+(?:also\s+|now\s+|directly\s+|already\s+)?(?P<verb>attacks|threatens|pins|hits)"
    rf"\s+(?:both\s+)?(?:the\s+)?(?P<adj>undefended\s+|unprotected\s+)?{_ph('t')}"
    rf"(?:\s*(?:,|and)\s*(?:and\s+)?(?P<adj2>undefended\s+)?{_ph('u')})?", re.IGNORECASE)
_ATTACK_EXPLICIT = re.compile(
    rf"\b{_ph('a')}\s+(?:also\s+|now\s+|directly\s+|already\s+)?"
    rf"(?P<verb>attacks|threatens|pins|hits)"
    rf"\s+(?:both\s+)?(?:the\s+)?(?P<adj>undefended\s+|unprotected\s+)?{_ph('t')}"
    rf"(?:\s*(?:,|and)\s*(?:and\s+)?(?P<adj2>undefended\s+)?{_ph('u')})?", re.IGNORECASE)
_CHECKS = [
    re.compile(rf"\b{_SUBJ}\s+(?:also\s+)?(?:gives|delivers)\s+(?:a\s+)?check\b", re.IGNORECASE),
    re.compile(rf"\b{_SUBJ}\s+(?:also\s+)?checks\s+(?:the\s+)?(?:white|black)\s+king\b", re.IGNORECASE),
]
_STATE = (r"(?P<state>undefended|unprotected|hanging|en prise|loose|attacked and undefended|"
          r"attacked more times than defended)")
_STATE_RE = re.compile(
    rf"{_ph('h')}(?:\s+and\s+{_ph('i')})?\s*,?\s+(?:which\s+)?"
    rf"(?:(?:is|are|remains?|was|now|becomes?|became|is\s+left|are\s+left)\s+"
    rf"(?:both\s+|also\s+|still\s+|now\s+|already\s+)*{_STATE}"
    rf"|(?:has|have)\s+no\s+(?P<nodef>defenders?|protection|support))", re.IGNORECASE)
_LEAVES = re.compile(
    rf"\bleaves\s+(?:the\s+)?{_ph('h')}\s+(?P<state>undefended|unprotected|hanging)", re.IGNORECASE)
_PRE_ADJ = re.compile(rf"\b(?P<state>undefended|unprotected|hanging)\s+{_ph('h')}", re.IGNORECASE)
_ATTACKED = re.compile(
    rf"{_ph('h')}\s+(?:is|are|remains|was)\s+(?:now\s+|also\s+|already\s+|still\s+)?"
    r"(?:under\s+attack|attacked)\b(?!\s+and\s+undefended)(?!\s+more)", re.IGNORECASE)
_PINNED = re.compile(rf"{_ph('n')}\s+(?:is|remains|was)\s+(?:currently\s+)?pinned", re.IGNORECASE)
_QUALITY = re.compile(
    rf"\b(?P<san>{SAN})\s+(?:was|is)\s+(?:rated\s+)?(?:a\s+|an\s+)?[\"']?"
    r"(?:significant\s+|serious\s+|big\s+|real\s+)?"
    r"(?P<v>blunder|mistake|inaccuracy|excellent|good|best)\b")
_WIN = re.compile(
    rf"\b(?P<subj>It|This\s+(?:\w+\s+)?move|The\s+move|{SAN}|White|Black)\s+"
    r"(?:also\s+|still\s+|effectively\s+)?(?P<verb>wins?|gains?|loses|costs?|captures?)\s+"
    r"(?:a\s+|an\s+|the\s+|significant\s+|some\s+|extra\s+|any\s+|(?:white|black)\s+)*"
    r"(?P<what>pawn|knight|bishop|rook|queen|piece|material)\b", re.IGNORECASE)
_ADVANTAGE = re.compile(
    r"\b(?P<subj>White|Black|It|This\s+(?:\w+\s+)?move)\s+(?:also\s+)?"
    r"gains?\s+(?:a\s+)?(?:significant\s+|clear\s+|big\s+)?material\s+advantage", re.IGNORECASE)
_IMPROVES = re.compile(r"\bimprov\w*\s+(?:the\s+)?material\s+balance", re.IGNORECASE)
_SHIFT = re.compile(
    r"(?:material\s+(?:shifts?|changes?)|shifts?\s+(?:the\s+)?material)\s+by\s+(?P<n>\d+)\s+points?"
    r"\s+in\s+(?P<side>white|black)'s\s+favou?r", re.IGNORECASE)
_SHIFT2 = re.compile(
    r"material\s+(?:advantage\s+)?(?:shift|swing)\s+of\s+(?P<n>\d+)\s+points?\s+"
    r"(?:for|in\s+favou?r\s+of|to)\s+(?P<side>white|black)"
    r"|shift\w*\s+(?:the\s+)?material(?:\s+advantage)?\s+(?:to|towards?)\s+(?P<side2>white|black)"
    r"\s+by\s+(?P<n2>\d+)\s+points?", re.IGNORECASE)
_NOCHANGE = re.compile(r"material\s+balance\s+(?:does\s+not|doesn't|did\s+not)\s+change|"
                       r"(?:does\s+not|doesn't)\s+(?:alter|change)\s+the\s+material", re.IGNORECASE)
_CHECK_CAPTURE = re.compile(
    rf"\b{_SUBJ}\s+(?:gives|delivers)\s+(?:a\s+)?check\s+and\s+(?:also\s+)?captures\s+"
    rf"(?:the\s+)?(?:(?:white|black)\s+)?(?P<pc>{PIECE})\b", re.IGNORECASE)
_MATES = [
    re.compile(rf"\b{_SUBJ}\s+(?:also\s+)?(?:is|delivers|gives|results\s+in|ends\s+in)\s+"
               r"(?:a\s+|an\s+)?(?:\w+\s+)?(?:checkmate|mate)\b", re.IGNORECASE),
    re.compile(rf"\b{_SUBJ}\s+(?:immediately\s+)?checkmates\b", re.IGNORECASE),
]
_THREAT_PIECE = re.compile(
    r"(?:fails?|failed|failing|does\s+not|doesn't|did\s+not)\s+(?:to\s+)?"
    r"(?:address|deal\s+with|stop|prevent|meet|handle|respond\s+to)\s+(?:the\s+)?(?:\w+\s+)?threat"
    rf"\s+(?:to|against)\s+{_ph('x')}"
    rf"|ignor\w+\s+(?:the\s+)?(?:\w+\s+)?threat\s+(?:to|against)\s+{_ph('y')}", re.IGNORECASE)
_THREAT_MOVE = re.compile(rf"\bthreat\s+of\s+(?P<san>{SAN})", re.IGNORECASE)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


@dataclass(frozen=True)
class FalseClaim:
    sentence: str
    problem: str  # plain words, fed back to the model when it is asked to rewrite


class _Malformed(Exception):
    pass


def _clean(san: str) -> str:
    return san.rstrip("+#")


def _piece(p: dict) -> tuple[bool, int, int]:
    try:
        color = {"white": chess.WHITE, "black": chess.BLACK}[p["color"].lower()]
        return color, _PIECES[p["piece"].lower()], chess.parse_square(p["square"].lower())
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        raise _Malformed(str(p)) from e


def _there(board: chess.Board, p: dict) -> bool:
    color, ptype, sq = _piece(p)
    got = board.piece_at(sq)
    return got is not None and got.piece_type == ptype and got.color == color


def _mates(board: chess.Board, move: chess.Move) -> bool:
    b = board.copy(stack=False)
    b.push(move)
    return b.is_checkmate()


def _holds(board: chess.Board, claim: dict) -> bool:
    """Is a board claim true on this board?"""
    t = claim["type"]
    if t == "attacks":
        ca, _, sa = _piece(claim["attacker"])
        ct, _, st = _piece(claim["target"])
        return (ca != ct and _there(board, claim["attacker"]) and _there(board, claim["target"])
                and sa in board.attackers(ca, st))
    if t in ("hanging", "undefended", "attacked", "pinned"):
        color, _, sq = _piece(claim["piece"])
        if not _there(board, claim["piece"]):
            return False
        if t == "undefended":
            return not board.attackers(color, sq)
        if t == "attacked":
            return bool(board.attackers(not color, sq))
        pool = cf.hanging_pieces(board, color) if t == "hanging" else cf.pins(board, color)
        return chess.square_name(sq) in {h["square"] for h in pool}
    if t in ("check", "checkmate"):
        try:
            move = board.parse_san(_clean(str(claim["move"])))
        except ValueError:
            return False
        return board.gives_check(move) if t == "check" else _mates(board, move)
    raise _Malformed(str(claim))


class _Ctx:
    """The positions and numbers a claim can be checked against, from the facts record."""

    def __init__(self, facts: dict, best_line_uci: list[str] | None) -> None:
        self.facts = facts
        self.start = chess.Board(facts["fen"])
        self.mover = self.start.turn
        self.played = chess.Move.from_uci(facts["played"]["uci"])
        best = facts.get("best")
        self.best = chess.Move.from_uci(best["uci"]) if best else self.played
        self.san = {"played": self.start.san(self.played), "best": self.start.san(self.best)}
        self.after = {"played": self._after(self.played), "best": self._after(self.best)}
        boards = truth_boards(facts["fen"], facts["played"]["uci"], best_line_uci or [])
        tb = threat_board(self.start)
        line_boards = boards[2:len(boards) - len(tb)]
        self.near = [self.start, self.after["played"], self.after["best"], *line_boards[:1], *tb]
        self.later = line_boards[1:]
        change = (facts.get("best_line") or {}).get("material_change_for_mover")
        self.line_change = change
        self.delta = {"best": change}
        if self.played == self.best:
            self.delta["played"] = change

    def _after(self, move: chess.Move) -> chess.Board:
        b = self.start.copy(stack=False)
        b.push(move)
        return b

    def move_of(self, ref: str) -> chess.Move:
        return self.played if ref == "played" else self.best

    def moved_piece(self, ref: str) -> chess.Piece | None:
        return self.after[ref].piece_at(self.move_of(ref).to_square)

    def ref_for_san(self, token: str) -> str | None:
        tok = _clean(token)
        if tok == _clean(self.san["played"]):
            return "played"
        return "best" if tok == _clean(self.san["best"]) else None


def _normalize(s: str) -> str:
    """Turn appositives into plain subjects: "The engine's best move, Nf7+, gives check" becomes
    "Nf7+ gives check", so the named move is the subject."""
    s = re.sub(rf"\b(?:[Tt]he\s+)?engine(?:'s)?\s+(?:best|preferred|top)\s+move,?\s+"
               rf"(?P<san>{SAN}),?(?=\s)", lambda m: m.group("san"), s)
    return re.sub(rf"\b(?:[Tt]he|[Tt]his)\s+(?:\w+\s+)?move,?\s+(?P<san>{SAN}),?(?=\s)",
                  lambda m: m.group("san"), s)


def _mentions(sentence: str, ctx: _Ctx) -> list[tuple[int, str]]:
    out = [(m.start(), ref) for m in _SAN_MENTION.finditer(sentence)
           if (ref := ctx.ref_for_san(m.group(1)))]
    out += [(m.start(), "best") for m in _BEST_PHRASE.finditer(sentence)]
    return sorted(out)


def _ref_at(sentence: str, pos: int, cur: str, ctx: _Ctx) -> str:
    before = [r for p, r in _mentions(sentence, ctx) if p < pos]
    return before[-1] if before else cur


def _subject_piece(subj: str, ref: str, ctx: _Ctx) -> dict | None:
    """The piece a subject such as "It" or "the knight" stands for, or None."""
    moved = ctx.moved_piece(ref)
    move = ctx.move_of(ref)
    if moved is None or ctx.start.is_castling(move):
        return None
    s = subj.strip().lower()
    if not re.fullmatch(r"it|which|this\s+(?:\w+\s+)?move|the\s+move", s):
        m = re.fullmatch(rf"(?:the\s+)?(?:(white|black)\s+)?({PIECE})", s)
        if not m or m.group(2) != chess.piece_name(moved.piece_type):
            return None
        if m.group(1) is not None and (m.group(1) == "white") != moved.color:
            return None
    return {"color": "white" if moved.color else "black",
            "piece": chess.piece_name(moved.piece_type), "square": chess.square_name(move.to_square)}


def _resolve(subj: str, pos: int, cur: str, ctx: _Ctx, s: str) -> str | None:
    """Which move ('played' or 'best') a claim's subject stands for, or None."""
    if re.fullmatch(SAN, subj):
        return ctx.ref_for_san(subj)
    ref = _ref_at(s, pos, cur, ctx)
    if re.fullmatch(r"(?i)it|which|this\s+(?:\w+\s+)?move|the\s+move", subj.strip()):
        return ref
    return ref if _subject_piece(subj, ref, ctx) else None


def _claims_in(orig: str, cur: str, ctx: _Ctx, prev_explicit: bool = False) -> list[dict]:
    s = _normalize(orig)
    claims: list[dict] = []

    def add(c: dict, ref: str | None = None) -> None:
        c["sentence"] = orig
        if ref:
            c["ref"] = ref
        claims.append(c)

    def emit_attack(m: re.Match, attacker: dict, ref: str | None) -> None:
        if m.group("verb").lower() == "pins":
            add({"type": "pinned", "piece": _pc(m, "t")}, ref)
            return
        add({"type": "attacks", "attacker": attacker, "target": _pc(m, "t")}, ref)
        if m.group("adj"):
            add({"type": "undefended", "piece": _pc(m, "t")}, ref)
        if m.group("cu"):
            add({"type": "attacks", "attacker": attacker, "target": _pc(m, "u")}, ref)
            if m.group("adj2"):
                add({"type": "undefended", "piece": _pc(m, "u")}, ref)

    for m in _ATTACK_EXPLICIT.finditer(s):
        emit_attack(m, _pc(m, "a"), None)
    for m in _ATTACK.finditer(s):
        subj = m.group("subj").strip().lower()
        if subj == "it" and prev_explicit:
            continue  # "It" most likely means the piece the previous sentence was about
        if subj == "which":
            named = list(_SAN_MENTION.finditer(s[:m.start()]))
            if not named or not re.fullmatch(r",?\s*", s[named[-1].end():m.start()]):
                continue  # "which" only binds to the move when it directly follows the move
        ref = _resolve(m.group("subj"), m.start(), cur, ctx, s)
        a = _subject_piece(m.group("subj"), ref, ctx) if ref else None
        if a is None and ref and re.fullmatch(SAN, m.group("subj")):
            moved = ctx.moved_piece(ref)
            move = ctx.move_of(ref)
            if moved is not None and not ctx.start.is_castling(move):
                a = {"color": "white" if moved.color else "black",
                     "piece": chess.piece_name(moved.piece_type),
                     "square": chess.square_name(move.to_square)}
        if a is None:
            continue
        emit_attack(m, a, ref)
    for rx in _CHECKS:
        for m in rx.finditer(s):
            ref = _resolve(m.group("subj") or "", m.start(), cur, ctx, s)
            if ref:
                add({"type": "check", "move": ctx.san[ref]}, ref)
    for rx in (_STATE_RE, _LEAVES, _PRE_ADJ):
        for m in rx.finditer(s):
            kind = ("undefended" if (m.group("state") or "undefended").lower() in _UNDEFENDED
                    else "hanging")
            add({"type": kind, "piece": _pc(m, "h")})
            if rx is _STATE_RE and m.group("ci"):
                add({"type": kind, "piece": _pc(m, "i")})
    for m in _ATTACKED.finditer(s):
        add({"type": "attacked", "piece": _pc(m, "h")})
    for m in _PINNED.finditer(s):
        add({"type": "pinned", "piece": _pc(m, "n")})
    for m in _QUALITY.finditer(s):
        word = m.group("v").lower()
        add({"type": "move_quality", "move": m.group("san"),
             "verdict": "bad" if word in ("blunder", "mistake", "inaccuracy") else "good"})
    for m in _WIN.finditer(s):
        subj, verb, what = m.group("subj"), m.group("verb").lower(), m.group("what").lower()
        side = subj.lower() if subj.lower() in ("white", "black") else None
        ref = cur if side else _resolve(subj, m.start(), cur, ctx, s)
        if ref is None:
            continue
        if verb.startswith("captur"):
            if what in _PIECES:
                add({"type": "captures", "piece": what}, ref)
            continue
        add({"type": "material", "win": verb.startswith(("win", "gain")), "what": what,
             "side": side}, ref)
    for m in _ADVANTAGE.finditer(s):
        subj = m.group("subj").lower()
        add({"type": "material", "win": True, "what": "material",
             "side": subj if subj in ("white", "black") else None}, _ref_at(s, m.start(), cur, ctx))
    for m in _IMPROVES.finditer(s):
        add({"type": "material", "win": True, "what": "material", "side": None},
            _ref_at(s, m.start(), cur, ctx))
    for m in _SHIFT.finditer(s):
        add({"type": "shift", "n": int(m.group("n")), "side": m.group("side").lower()})
    for m in _SHIFT2.finditer(s):
        add({"type": "shift", "n": int(m.group("n") or m.group("n2")),
             "side": (m.group("side") or m.group("side2")).lower()})
    if _NOCHANGE.search(s):
        add({"type": "shift", "n": 0, "side": None})
    for m in _CHECK_CAPTURE.finditer(s):
        ref = _resolve(m.group("subj"), m.start(), cur, ctx, s)
        if ref:
            add({"type": "captures", "piece": m.group("pc").lower()}, ref)
    for rx in _MATES:
        for m in rx.finditer(s):
            ref = _resolve(m.group("subj"), m.start(), cur, ctx, s)
            if ref:
                add({"type": "checkmate", "move": ctx.san[ref]}, ref)
    for m in _THREAT_PIECE.finditer(s):
        add({"type": "threat", "piece": _pc(m, "x") if m.group("cx") else _pc(m, "y")}, "played")
    for m in _THREAT_MOVE.finditer(s):
        add({"type": "threat_move", "move": m.group("san")}, "played")
    return claims


def extract_claims(text: str, ctx: _Ctx) -> list[dict]:
    claims: list[dict] = []
    cur = "played"
    prev_explicit = False
    for sentence in _SPLIT.split(text.strip()):
        if not sentence:
            continue
        claims += _claims_in(sentence, cur, ctx, prev_explicit)
        prev_explicit = bool(re.match(rf"\s*{_ph('z')}", sentence, re.IGNORECASE))
        named = _mentions(_normalize(sentence), ctx)
        if named:
            cur = named[-1][1]
    return claims


def _name(p: dict) -> str:
    return f"{p['color']} {p['piece']} on {p['square']}"


def _problem(claim: dict, ctx: _Ctx) -> str | None:
    """None when the claim is true or cannot be checked, otherwise what is wrong with it."""
    t = claim["type"]
    if t == "move_quality":
        if _clean(claim["move"]) != _clean(ctx.san["played"]):
            return None
        label = ctx.facts["classification"]
        if (claim["verdict"] == "good") != (label in _GOOD):
            return f"the engine rates {claim['move']} as {label}"
        return None
    if t == "shift":
        change = ctx.line_change
        if change is None:
            return None
        favoured = "white" if (change > 0) == bool(ctx.mover) else "black"
        if claim["n"] == 0:
            return (None if change == 0 else
                    f"the engine's best line shifts material by {abs(change)} points")
        if abs(change) == claim["n"] and favoured == claim["side"]:
            return None
        return (f"the engine's best line shifts material by {abs(change)} points in "
                f"{favoured}'s favour, not {claim['n']} in {claim['side']}'s")
    if t == "captures":
        move = ctx.move_of(claim["ref"])
        got = ctx.start.piece_at(move.to_square)
        if got is not None and chess.piece_name(got.piece_type) == claim["piece"]:
            return None
        return f"{ctx.san[claim['ref']]} does not capture a {claim['piece']}"
    if t == "material":
        d = ctx.delta.get(claim["ref"])
        if d is None:
            return None
        side_color = ctx.mover if claim["side"] is None else (claim["side"] == "white")
        d_side = d if side_color == ctx.mover else -d
        need = _VALUE[claim["what"]]
        if (d_side >= need) if claim["win"] else (d_side <= -need):
            return None
        side = "White" if side_color else "Black"
        return (f"the engine line does not show {side} "
                f"{'winning' if claim['win'] else 'losing'} material")
    if t == "threat":
        color, ptype, sq = _piece(claim["piece"])
        after = ctx.after["played"]
        p = after.piece_at(sq)
        if p and p.color == color and p.piece_type == ptype and after.attackers(not color, sq):
            return None
        return f"nothing attacks the {_name(claim['piece'])} after the move"
    if t == "threat_move":
        for board in (ctx.after["played"], ctx.start):
            try:
                move = board.parse_san(_clean(claim["move"]))
            except ValueError:
                continue
            if not claim["move"].endswith("#") or _mates(board, move):
                return None
        return f"{claim['move']} is not possible here"
    if any(_holds(b, claim) for b in ctx.near + ctx.later):
        return None
    return _board_problem(claim)


def _board_problem(claim: dict) -> str:
    t = claim["type"]
    if t == "attacks":
        return f"the {_name(claim['attacker'])} does not attack the {_name(claim['target'])}"
    if t == "undefended":
        return f"the {_name(claim['piece'])} is defended"
    if t == "hanging":
        return f"the {_name(claim['piece'])} is not hanging"
    if t == "attacked":
        return f"the {_name(claim['piece'])} is not attacked"
    if t == "pinned":
        return f"the {_name(claim['piece'])} is not pinned"
    if t == "check":
        return f"{claim['move']} does not give check"
    return f"{claim['move']} is not checkmate"


def find_false_claims(
    text: str, facts: dict, best_line_uci: list[str] | None = None
) -> list[FalseClaim]:
    """Claims in `text` that the position or the engine line contradicts."""
    try:
        ctx = _Ctx(facts, best_line_uci)
    except (KeyError, ValueError):  # a facts record we cannot read: say nothing
        return []
    out: list[FalseClaim] = []
    seen: set[str] = set()
    for claim in extract_claims(text, ctx):
        try:
            problem = _problem(claim, ctx)
        except _Malformed:
            continue
        if problem and problem not in seen:
            seen.add(problem)
            out.append(FalseClaim(sentence=claim["sentence"], problem=problem))
    return out
