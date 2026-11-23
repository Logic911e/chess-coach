"""Turn a facts record into short, plain-English statements, with no model involved.

Why: a small model that reads raw JSON has to work out who owns which piece and what a field
like "why: worth more" means, and that is where it goes wrong. Here code does that work once,
spelling out colour and square, so the model's only job is to rewrite statements that are
already true.
"""

from __future__ import annotations


def _name(color: str) -> str:
    return color.capitalize()


def _other(color: str) -> str:
    return "black" if color == "white" else "white"


def _piece(color: str, item: dict) -> str:
    return f"{color} {item['piece']} on {item['square']}"


_FORK_WHY = {
    "undefended": "which has no defender",
    "worth more": "which is worth more than the attacking piece",
}


def _move_statements(m: dict, mover: str, opp: str, who: str) -> list[str]:
    """Statements about one move. `who` is 'The move played' or 'The engine's best move'."""
    out = []
    desc = f"{m['piece']} from {m['from']} to {m['to']}"
    if m["castling"]:
        desc = "castling"
    if m["captures"]:
        desc += f", capturing a {m['captures']}"
    if m["promotion"]:
        desc += f", promoting to a {m['promotion']}"
    out.append(f"{who} is {m['san']} ({desc}).")
    if m["checkmate"]:
        out.append(f"{m['san']} is checkmate.")
    elif m["gives_check"]:
        out.append(f"{m['san']} gives check.")
    for f in m["forks"]:
        why = _FORK_WHY.get(f["why"], f["why"])
        out.append(f"After {m['san']}, the {mover} {m['piece']} on {m['to']} attacks the "
                   f"{_piece(opp, f)}, {why}.")
    for h in m["leaves_own_piece_hanging"]:
        out.append(f"After {m['san']}, the {_piece(mover, h)} is {h['reason']}.")
    for t in m["ignored_threats"]:
        out.append(f"The {_piece(mover, t)} was already under threat ({t['reason']}), "
                   f"and {m['san']} does not deal with that threat.")
    for h in m["enemy_pieces_hanging_after"]:
        out.append(f"After {m['san']}, the {_piece(opp, h)} is {h['reason']}.")
    return out


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _points(n: int) -> str:
    return f"{n} point" + ("" if n == 1 else "s")


def _rich_statements(facts: dict) -> list[str]:
    """Extra statements from facts that are already in the record (material, hanging pieces,
    king safety, development, material along the engine line). They give the model real things
    to say about a quiet position, so it has less reason to invent."""
    mover = facts["side_to_move"]
    out = []
    balance = facts["material_balance_white_minus_black"]
    scale = "(pawn 1, knight 3, bishop 3, rook 5, queen 9)"
    if balance == 0:
        out.append(f"In the starting position, material is level {scale}.")
    else:
        ahead = "white" if balance > 0 else "black"
        out.append(f"In the starting position, {_name(ahead)} is ahead by "
                   f"{_points(abs(balance))} of material {scale}.")
    for color in ("white", "black"):
        side = facts["position"][color]
        for h in side["hanging_pieces"]:
            out.append(f"In the starting position, the {_piece(color, h)} is {h['reason']}.")
        ks = side["king_safety"]
        if ks:
            king = f"the {color} king on {ks['king_square']}"
            if ks["pawn_shield"] <= 1:
                n = ks["pawn_shield"]
                out.append(f"{_cap(king)} has {n} of its own pawn{'' if n == 1 else 's'} "
                           "directly in front of it.")
            if ks["king_file_open"]:
                out.append(f"There is no {color} pawn on the file of {king}.")
            n = ks["enemy_pieces_attacking_king_zone"]
            if n >= 2:  # one attacker is normal in the opening, so it is not worth a statement
                out.append(f"{n} {_other(color)} pieces attack squares next to {king}.")
        count = side["undeveloped_minor_pieces"]
        if count and _early(facts["fen"]):
            if count == 1:
                out.append(f"{_name(color)} still has 1 minor piece (a knight or bishop) on its "
                           "starting square.")
            else:
                out.append(f"{_name(color)} still has {count} minor pieces (knights or bishops) "
                           "on their starting squares.")
    line = facts.get("best_line")
    if line:
        change = line["material_change_for_mover"]
        if change == 0:
            out.append("The material balance does not change along the engine's best line.")
        else:
            favoured = mover if change > 0 else _other(mover)
            out.append(f"Along the engine's best line, material shifts by {_points(abs(change))}"
                       f" in {favoured}'s favour.")
    return out


def _early(fen: str) -> bool:
    """Development counts only mean something early in the game (first 12 moves)."""
    return int(fen.split()[5]) <= 12


def render_facts(facts: dict, rich: bool = False) -> list[str]:
    """Every statement is derived from the facts record; nothing is added.

    `rich` appends statements about material, hanging pieces, king safety and development."""
    mover = facts["side_to_move"]
    opp = _other(mover)
    played, best = facts["played"], facts.get("best")
    label, lost = facts["classification"], facts["expected_points_lost"]
    out = [
        (
            f'{_name(mover)} to move. The move is rated "{label}", losing {lost} expected points '
            "(0 = no loss, 1 = the whole game)."
        )
    ]
    out += _move_statements(played, mover, opp, "The move played")
    if best:  # build_facts only includes "best" when it differs from the move played
        out += _move_statements(best, mover, opp, "The engine's best move")
    else:
        out.append("The move played is also the engine's best move.")
    line = facts.get("best_line")
    if line:
        out.append(f"The engine's best line is {line['line_san']}.")
        if line["ends_in_checkmate"]:
            out.append("That line ends in checkmate.")
    for color in ("white", "black"):
        side = facts["position"][color]
        for p in side["pinned_pieces"]:
            out.append(f"In the starting position, the {_piece(color, p)} is pinned by the "
                       f"{_other(color)} {p['pinned_by']}.")
        for p in side["passed_pawns"]:
            sq = p["square"] if isinstance(p, dict) else p
            out.append(f"{_name(color)} has a passed pawn on {sq}.")
    if rich:
        out += _rich_statements(facts)
    return out
