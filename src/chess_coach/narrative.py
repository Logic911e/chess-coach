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


def render_facts(facts: dict) -> list[str]:
    """Every statement is derived from the facts record; nothing is added."""
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
    return out
